from download import Download
from notion import Notion
from upload import Upload
from migrate import MigrationTask
from batch_rename import BatchRemoveSuffixTask
from page_size_update import PageSizeUpdateTask, scan_pages_for_size_property
from logger import PythonLogger

class Main:
    def __init__(self, notion_token: str, max_download_workers: int = 3, max_upload_workers: int = 3, url="https://api.notion.com/v1", log_dir: str = None):
        # 初始化日志系统（如果提供了日志目录）
        if log_dir:
            PythonLogger.init(log_dir)
            self.logger = PythonLogger.get_logger()
        else:
            self.logger = PythonLogger.get_logger()
        
        url = url.rstrip('/')  # 确保 URL 没有尾部斜杠
        self.notion = Notion(notion_token, url=url)
        self.downloader = Download(max_workers=max_download_workers)
        self._probe_id = None
        self.download_list = []
        self.Uploader = Upload(
            notion_token=self.notion.token,
            max_workers=max_upload_workers,
            rps=3.0,
            burst=4,
            part_size_bytes=15 * 1024 * 1024,
            debug=True,
            url=url,
        )
        self._probe_size_map = {}
        self._migration_task: MigrationTask | None = None
        self._batch_rename_task: BatchRemoveSuffixTask | None = None
        self._page_size_task: PageSizeUpdateTask | None = None
        
        self.logger.info(f"Main initialized: dl_workers={max_download_workers}, ul_workers={max_upload_workers}, url={url}")
    # -------------------------
    # Download
    # -------------------------
    def get_download_list(self, page_id: str):
        """
        发起：拉取 Notion 页面文件列表 + 异步探测 size
        v1.4.2: 扩展支持所有媒体块 (file/image/pdf/audio/video) + 页面级文件 (icon/cover/files属性)
        返回：Success + probe_id（前端后续用 probe_id 轮询进度）
        """
        page_data = self.notion.query_page(page_id, True)
        self.download_list = self.notion.get_download_url(page_data)

        # v1.4.2: 获取页面对象，提取 icon/cover/files 属性
        try:
            page_obj = self.notion.get_page_object(page_id)
            if page_obj:
                page_level_files = self.notion.extract_page_level_files(page_obj)
                if page_level_files:
                    self.download_list.extend(page_level_files)
                    self.logger.info(f"Page-level files found: {len(page_level_files)} (icon/cover/property files)")
        except Exception as e:
            self.logger.warning(f"Page-level file extraction failed (non-fatal): {e}")

        urls = [f["url"] for f in self.download_list if f.get("url")]
        if urls:
            self._probe_id = self.downloader.start_probe_sizes(urls, timeout=10, max_retries=3)
            return {
                "status": "success",
                "msg": "下载列表已获取，正在探测文件大小",
                "probe_id": self._probe_id,
                "total": len(urls),
            }
        else:
            self._probe_id = None
            return {
                "status": "success",
                "msg": "下载列表为空",
                "probe_id": None,
                "total": 0,
            }
    # -------------------------
    # Streaming Download List (v1.5.1-Status.6)
    # -------------------------
    def start_download_list_streaming(self, page_id: str, probe_workers: int = 8):
        """
        流式获取文件列表：启动后台线程递归扫描页面，
        每发现一批文件立即追加到 self.download_list 并即时开始探测大小。
        前端可随时读取增量和实时大小。
        v1.5.2: 扫描与探测并行，边发现边探测。
        """
        import threading
        import queue as _queue

        self.download_list = []
        self._scan_lock = threading.Lock()
        self._scan_status = {
            "status": "scanning",
            "discovered": 0,
            "done": False,
            "error": None,
            "probe_id": None,
            "total_urls": 0,
            "files_probed": 0,
            "probing_done": False,  # _probe_consumer 全部完成后设为 True
        }
        self._probe_id = None
        self._stream_probe_queue = _queue.Queue()
        self._scan_cancelled = False  # 取消标志，_worker/_probe_consumer 轮询此标志

        def _probe_consumer():
            """消费者线程：从队列取出 URL，立即探测大小并回写 download_list"""
            from concurrent.futures import ThreadPoolExecutor

            pool = ThreadPoolExecutor(max_workers=probe_workers)
            futures = []

            def _probe_one(item_ref, url):
                # 已取消则跳过
                if self._scan_cancelled:
                    return
                # 复用 self.downloader._probe_one（urllib 双策略：HEAD Content-Length → Range GET Content-Range）
                # 避免使用 requests 库——Notion S3 签名 URL 在 requests HEAD 响应中不返回 Content-Length，
                # Range GET 在部分情况下也无法获取 Content-Range，导致所有文件大小探测结果为 0。
                size_mb = None
                try:
                    size_mb = self.downloader._probe_one(url, timeout=10)
                except Exception as e:
                    self.logger.warning(f"[PROBE] _probe_one exception: {e!r}, url_tail={url[-60:]!r}")

                item_ref["size_mb"] = size_mb if size_mb is not None else 0.0
                with self._scan_lock:
                    self._scan_status["files_probed"] = self._scan_status.get("files_probed", 0) + 1

            while True:
                # 取消时立即退出，不再提交新探测任务
                if self._scan_cancelled:
                    break
                try:
                    msg = self._stream_probe_queue.get(timeout=0.5)
                except _queue.Empty:
                    # Check if scan is done and queue is empty
                    with self._scan_lock:
                        if self._scan_status["done"] and self._stream_probe_queue.empty():
                            break
                    continue

                if msg is None:  # poison pill
                    break
                item_ref, url = msg
                futures.append(pool.submit(_probe_one, item_ref, url))

            # 取消时 cancel 所有还未开始的 future，正在执行的等它自然结束（urllib timeout 兜底）
            if self._scan_cancelled:
                for f in futures:
                    f.cancel()
                pool.shutdown(wait=False)
            else:
                # Wait for all probes to finish
                for f in futures:
                    try:
                        f.result(timeout=30)
                    except Exception:
                        pass
                pool.shutdown(wait=False)

            # Mark probing done
            with self._scan_lock:
                self._scan_status["probing_done"] = True

        def _worker():
            try:
                self._scan_blocks_streaming(page_id)

                # 获取页面级文件（icon/cover/files 属性）
                try:
                    page_obj = self.notion.get_page_object(page_id)
                    if page_obj:
                        pf = self.notion.extract_page_level_files(page_obj)
                        if pf:
                            with self._scan_lock:
                                self.download_list.extend(pf)
                                self._scan_status["discovered"] = len(self.download_list)
                            # Queue page-level files for probing
                            for item in pf:
                                url = item.get("url", "")
                                if url:
                                    self._stream_probe_queue.put((item, url))
                except Exception as e:
                    self.logger.warning(f"Page-level files extraction failed (non-fatal): {e}")

                self.logger.info(f"Streaming scan completed: {len(self.download_list)} files")

                # 扫描完成后，发送毒丸通知 _probe_consumer 扫描已结束。
                # _probe_consumer 会等待队列中所有已提交的探测任务完成，然后自行设置 probing_done=True。
                # 不再重复启动传统 start_probe_sizes，避免对全部 URL 重复探测一遍。
                self._stream_probe_queue.put(None)

                total_urls = sum(1 for f in self.download_list if f.get("url"))
                with self._scan_lock:
                    self._scan_status["total_urls"] = total_urls
                    self._scan_status["status"] = "probing" if total_urls else "done"
                    self._scan_status["done"] = True  # 扫描完成，_probe_consumer 探测仍在后台继续

            except Exception as e:
                self.logger.error(f"Streaming scan failed: {e}")
                with self._scan_lock:
                    self._scan_status.update({
                        "status": "error",
                        "error": str(e),
                        "done": True,
                    })
                self._stream_probe_queue.put(None)

        # Start probe consumer first, then scanner
        threading.Thread(target=_probe_consumer, daemon=True).start()
        threading.Thread(target=_worker, daemon=True).start()
        return {"status": "scanning", "msg": "开始流式扫描页面文件"}

    def _scan_blocks_streaming(self, page_id: str):
        """
        递归扫描某页面的所有 blocks。
        每一层获取到 blocks 后，立即提取文件链接追加到 download_list，
        并将每个文件推入探测队列以便即时探测大小，
        然后继续递归有子块的 block。
        """
        # 不使用 fetch_all=True（那会一次性递归完才返回）
        blocks = self.notion.query_page(page_id, fetch_all=False)

        # 立即提取当前层级的文件（不递归、不探大小）
        files = self.notion.get_download_url_no_recurse(blocks)
        if files:
            with self._scan_lock:
                self.download_list.extend(files)
                self._scan_status["discovered"] = len(self.download_list)
            # Queue each file for immediate size probing
            for item in files:
                url = item.get("url", "")
                if url:
                    self._stream_probe_queue.put((item, url))

        # 递归有子块的 block
        for block in blocks:
            if self._scan_cancelled:  # 取消时停止递归
                return
            if block.get("has_children"):
                self._scan_blocks_streaming(block["id"])

    def get_download_list_scan_status(self):
        """返回当前流式扫描的状态（线程安全）"""
        lock = getattr(self, "_scan_lock", None)
        status = getattr(self, "_scan_status", None)
        if lock is None or status is None:
            return {
                "status": "not_started",
                "discovered": 0,
                "done": False,
                "error": None,
                "probe_id": None,
                "total_urls": 0,
                "files_probed": 0,
            }
        with lock:
            result = dict(status)
        return result

    def cancel_download_list_streaming(self):
        """取消正在进行的流式扫描和探测（线程安全）"""
        self._scan_cancelled = True
        # 往队列塞毒丸，让 _probe_consumer 尽快从 get() 阻塞中退出
        try:
            self._stream_probe_queue.put_nowait(None)
        except Exception:
            pass
        self.logger.info("[SCAN] cancel_download_list_streaming called")

    def download_list_processing(self, probe_id: str | None = None):
        """
        返回：
        {
        "status": ...,
        "percent": ...,
        "done": ...,
        "total": ...,
        "error": ...,
        }
        同时回写 self.download_list 的 size_mb
        """
        pid = probe_id or self._probe_id
        if not pid:
            return {
                "status": "not_started",
                "percent": 0.0,
                "done": 0,
                "total": 0,
                "error": None,
            }

        progress = self.downloader.get_probe_progress(pid)

        size_map = self.downloader.get_probe_results(pid, partial=True)
        self._probe_size_map = size_map

        wrote_count = 0
        if size_map:
            for item in self.download_list:
                url = item.get("url")
                if not url:
                    continue
                probed = size_map.get(url)
                if probed is not None:
                    item["size_mb"] = probed
                    wrote_count += 1
        self.logger.info(f"download_list_processing: probe_id={pid}, wrote {wrote_count}/{len(self.download_list)} sizes")

        return {
            "status": progress.get("status", "probing"),
            "percent": float(progress.get("progress", 0.0)),
            "done": int(progress.get("done", 0)),
            "total": int(progress.get("total", 0)),
            "error": progress.get("errors"),
        }

    def cancel_download_list_probe(self):
        """
        取消当前下载列表的大小探测任务。
        前端点击"取消"时调用，确保 Python 侧的探测线程也能尽快停止。
        """
        pid = self._probe_id
        if pid:
            cancelled = self.downloader.cancel_probe(pid)
            self.logger.info(f"cancel_download_list_probe: probe_id={pid}, cancelled={cancelled}")
            self._probe_id = None
        else:
            self.logger.info("cancel_download_list_probe: no active probe")

    def _make_url_refresh_callback(self, block_id: str):
        """
        创建一个 URL 刷新回调闭包。
        当下载链接过期时，通过 block_id 重新向 Notion API 请求新链接。
        """
        def _refresh() -> str | None:
            result = self.notion.refresh_file_url(block_id)
            if result and result.get("url"):
                return result["url"]
            return None
        return _refresh

    def download_notion_files(self, download_list, save_directory: str):
        """
        启动下载任务（批量）
        对每个有 block_id 的文件，传入 URL 刷新回调，
        使下载器在链接过期时能自动刷新并重试。
        """
        self.download_list = download_list

        for file_info in self.download_list:
            url = file_info["url"]
            real_name = file_info["real_name"]
            save_path = f"{save_directory}/{real_name}"
            size_mb = file_info.get("size_mb", 0.0)
            block_id = file_info.get("block_id", "")

            # 如果有 block_id，创建刷新回调；否则为 None（不支持刷新）
            refresh_cb = self._make_url_refresh_callback(block_id) if block_id else None

            self.downloader.download(url, save_path, size=size_mb,
                                     url_refresh_callback=refresh_cb,
                                     max_url_refresh=2)

        return "Download tasks started"

    def get_download_statuses(self):
        """
        返回下载状态列表（包含 created_time, block_type）
        """
        statuses = []
        for file_info in self.download_list:
            url = file_info["url"]
            name = file_info.get("name")
            real_name = file_info.get("real_name")
            created_time = file_info.get("created_time")
            block_type = file_info.get("block_type", "file")

            status_info = self.downloader.get_status(url)  # 以 url 为 key

            statuses.append({
                "url": url,
                "name": name,
                "real_name": real_name,
                "status": status_info.get("status", "not_found"),
                "progress": status_info.get("progress", 0),
                "downloaded_mb": status_info.get("downloaded_mb", 0.0),
                "total_mb": status_info.get("total_mb", 0.0),
                "speed_mb_s": status_info.get("speed_mb_s", 0.0),
                "usedTime": status_info.get("usedTime", 0),
                "ETA": status_info.get("ETA", 0),
                "error": status_info.get("error"),
                "created_time": created_time,
                "block_type": block_type,
            })
        return statuses

    # -------------------------
    # Upload
    # -------------------------
    def upload_notion_files(self, page_id: str, files_list: list[str]):
        """
        启动上传任务（批量）
        """
        

        ok, fail = 0, 0
        for file_path in files_list:
            ret = self.Uploader.upload_file(file_path, page_id)

            if isinstance(ret, dict) and ret.get("msg") in {"任务已入队", "任务已提交"}:
                ok += 1
            else:
                fail += 1

        if fail > 0:
            return f"Success {ok}, Failed {fail}"
        return "Success"

    def upload_folder(self, page_id: str, folder_path: str):
        """
        上传整个文件夹到 Notion 页面。
        - 根目录下的文件直接上传到 page_id
        - 子文件夹在 page_id 下创建同名子页面，递归上传
        返回: { "status": "success", "files": int, "pages_created": int, "failed": int }
        """
        import os

        if not os.path.isdir(folder_path):
            return {"status": "error", "msg": f"文件夹不存在: {folder_path}"}

        total_files = 0
        total_pages = 0
        total_failed = 0

        def _upload_dir(dir_path: str, target_page_id: str):
            nonlocal total_files, total_pages, total_failed

            entries = sorted(os.listdir(dir_path))
            files_in_dir = []
            subdirs = []

            for entry in entries:
                full_path = os.path.join(dir_path, entry)
                if os.path.isfile(full_path):
                    files_in_dir.append(full_path)
                elif os.path.isdir(full_path):
                    subdirs.append((entry, full_path))

            # 上传当前目录的文件
            for fp in files_in_dir:
                try:
                    ret = self.Uploader.upload_file(fp, target_page_id)
                    if isinstance(ret, dict) and ret.get("msg") in {"任务已入队", "任务已提交"}:
                        total_files += 1
                    else:
                        total_failed += 1
                        self.logger.warning(f"[upload_folder] 文件入队失败: {fp}, ret={ret}")
                except Exception as e:
                    total_failed += 1
                    self.logger.error(f"[upload_folder] 文件上传异常: {fp}, err={e}")

            # 处理子文件夹：创建子页面后递归
            for subdir_name, subdir_path in subdirs:
                try:
                    child_page = self.notion.create_child_page(target_page_id, subdir_name)
                    child_page_id = child_page.get("id", "")
                    if not child_page_id:
                        self.logger.error(f"[upload_folder] 创建子页面失败，无 id: {subdir_name}")
                        total_failed += 1
                        continue
                    total_pages += 1
                    self.logger.info(f"[upload_folder] 创建子页面: '{subdir_name}' -> {child_page_id}")
                    _upload_dir(subdir_path, child_page_id)
                except Exception as e:
                    total_failed += 1
                    self.logger.error(f"[upload_folder] 创建子页面异常: {subdir_name}, err={e}")

        _upload_dir(folder_path, page_id)

        msg = f"已入队 {total_files} 个文件"
        if total_pages > 0:
            msg += f"，创建了 {total_pages} 个子页面"
        if total_failed > 0:
            msg += f"，{total_failed} 个失败"

        self.logger.info(f"[upload_folder] 完成: files={total_files}, pages={total_pages}, failed={total_failed}")
        return {
            "status": "success" if total_failed == 0 else "partial",
            "msg": msg,
            "files": total_files,
            "pages_created": total_pages,
            "failed": total_failed,
        }

    def get_upload_statuses(self):
        """
        返回上传状态列表
        """
        """
        上传状态格式:
        [

            {
                "file_path": "C:/path/to/file.ext",
                "status": "uploading",
                "stage": "uploading",
                "progress": 50.0,
                "uploaded_mb": 1.25,
                "total_mb": 2.5,
                "speed_mb_s": 0.5,
                "usedTime": 10,
                "ETA": 10,
                "error": null
            }
        ]
        """
        if not self.Uploader:
            return []

        get_statuses = self.Uploader.list_status()
        statuses = []
        for status in get_statuses:
            statuses.append({
                "file_path": status.get("file_path"),
                "status": status.get("status"),
                "stage": status.get("stage"),
                "progress": status.get("progress", 0),
                "uploaded_mb": status.get("uploaded_mb", 0.0),
                "total_mb": status.get("total_mb", 0.0),
                "speed_mb_s": status.get("speed_mb_s", 0.0),
                "usedTime": status.get("usedTime", 0),
                "ETA": status.get("ETA", 0),
                "error": status.get("error"),
            })
        return statuses

    # -------------------------
    # Migration (v1.3.0-Status)
    # -------------------------
    def get_database_properties(self, data_source_id: str):
        """
        获取数据源属性 Schema。
        返回: {
            "status": "success" | "error",
            "data_source_id": "...",
            "title": "...",
            "properties": { "属性名": {"id": "...", "type": "..."}, ... },
            "error": "..." (仅在 status=error 时)
        }
        """
        return self.notion.get_database_properties(data_source_id)

    def start_migration(self, source_id: str, target_id: str, property_mapping: dict, max_workers: int = 3):
        """
        启动后台迁移任务。
        
        参数:
            source_id:        源数据源 ID
            target_id:        目标数据源 ID
            property_mapping: 属性映射 {源属性名: 目标属性名}
            max_workers:      并发线程数
        
        返回: {"status": "started"} 或 {"status": "error", "error": "..."}
        """
        # 如果有正在运行的迁移任务，先检查状态
        if self._migration_task is not None:
            progress = self._migration_task.get_progress()
            if progress["status"] in ("querying", "migrating"):
                return {"status": "error", "error": "已有迁移任务正在运行，请先等待完成或取消"}

        self._migration_task = MigrationTask(
            notion=self.notion,
            source_id=source_id,
            target_id=target_id,
            property_mapping=property_mapping,
            max_workers=max_workers,
        )

        result = self._migration_task.start()
        self.logger.info(f"Migration started: {source_id} -> {target_id}, mapping={property_mapping}, workers={max_workers}")
        return result

    def get_migration_progress(self):
        """
        查询迁移进度。
        返回: {
            "status": "idle" | "querying" | "migrating" | "done" | "cancelled" | "error",
            "total": int,
            "done": int,
            "failed": int,
            "percent": float,
            "errors": list[str]
        }
        """
        if self._migration_task is None:
            return {
                "status": "idle",
                "total": 0,
                "done": 0,
                "failed": 0,
                "percent": 0.0,
                "errors": [],
            }
        return self._migration_task.get_progress()

    def cancel_migration(self):
        """
        取消迁移任务。
        返回: {"status": "cancelled"} 或 {"status": "idle"}
        """
        if self._migration_task is None:
            return {"status": "idle"}
        result = self._migration_task.cancel()
        self.logger.info("Migration cancelled by user")
        return result

    # -------------------------
    # Batch Remove Suffix (v1.3.0-Status)
    # -------------------------
    def start_batch_remove_suffix(self, data_source_id: str, suffix: str, max_workers: int = 3):
        """
        启动批量去除后缀任务。

        参数:
            data_source_id: 数据源 ID
            suffix:         要去除的后缀字符串（如 "(1)"）
            max_workers:    并发线程数

        返回: {"status": "started"} 或 {"status": "error", "error": "..."}
        """
        if self._batch_rename_task is not None:
            progress = self._batch_rename_task.get_progress()
            if progress["status"] in ("querying", "processing"):
                return {"status": "error", "error": "已有批量去除后缀任务正在运行，请先等待完成或取消"}

        self._batch_rename_task = BatchRemoveSuffixTask(
            notion=self.notion,
            data_source_id=data_source_id,
            suffix=suffix,
            max_workers=max_workers,
        )

        result = self._batch_rename_task.start()
        self.logger.info(f"BatchRemoveSuffix started: ds={data_source_id}, suffix='{suffix}', workers={max_workers}")
        return result

    def get_batch_remove_suffix_progress(self):
        """
        查询批量去除后缀进度。
        返回: {
            "status": "idle" | "querying" | "processing" | "done" | "cancelled" | "error",
            "total": int,       # 匹配后缀的页面数
            "scanned": int,     # 扫描的页面总数
            "done": int,        # 成功更新的页面数
            "failed": int,
            "skipped": int,     # 不含后缀的页面数
            "percent": float,
            "errors": list[str]
        }
        """
        if self._batch_rename_task is None:
            return {
                "status": "idle",
                "total": 0,
                "scanned": 0,
                "done": 0,
                "failed": 0,
                "skipped": 0,
                "percent": 0.0,
                "errors": [],
            }
        return self._batch_rename_task.get_progress()

    def cancel_batch_remove_suffix(self):
        """
        取消批量去除后缀任务。
        返回: {"status": "cancelled"} 或 {"status": "idle"}
        """
        if self._batch_rename_task is None:
            return {"status": "idle"}
        result = self._batch_rename_task.cancel()
        self.logger.info("BatchRemoveSuffix cancelled by user")
        return result

    # -------------------------
    # Page Size Update (v1.4.0-Status)
    # -------------------------
    def scan_data_source_pages(self, data_source_id: str, size_property_name: str):
        """
        扫描数据源所有页面，按大小属性是否已设置分类。

        参数:
            data_source_id:    数据源 ID
            size_property_name: 大小属性名

        返回: {
            "status": "success" | "error",
            "pages_with_size": [{"id": "...", "title": "...", "size_value": 123.45}, ...],
            "pages_without_size": [{"id": "...", "title": "..."}, ...],
            "total": int,
            "error": "..."
        }
        """
        self.logger.info(f"scan_data_source_pages: ds={data_source_id}, prop={size_property_name}")
        return scan_pages_for_size_property(self.notion, data_source_id, size_property_name)

    def start_page_size_update(
        self,
        data_source_id: str,
        size_property_name: str,
        page_ids: list[str],
        link_workers: int = 3,
        size_workers: int = 5,
    ):
        """
        启动页面大小自动更新任务。

        参数:
            data_source_id:    数据源 ID
            size_property_name: 大小属性名 (number 类型)
            page_ids:          要更新的页面 ID 列表
            link_workers:      链接查询线程数 (默认 3)
            size_workers:      大小查询线程数 (默认 5)

        返回: {"status": "started"} 或 {"status": "error", "error": "..."}
        """
        if self._page_size_task is not None:
            progress = self._page_size_task.get_progress()
            if progress["status"] in ("scanning", "updating"):
                return {"status": "error", "error": "已有页面大小更新任务正在运行，请先等待完成或取消"}

        self._page_size_task = PageSizeUpdateTask(
            notion=self.notion,
            data_source_id=data_source_id,
            size_property_name=size_property_name,
            page_ids=page_ids,
            link_workers=link_workers,
            size_workers=size_workers,
        )

        result = self._page_size_task.start()
        self.logger.info(
            f"PageSizeUpdate started: ds={data_source_id}, prop={size_property_name}, "
            f"pages={len(page_ids)}, link_workers={link_workers}, size_workers={size_workers}"
        )
        return result

    def get_page_size_update_progress(self):
        """
        查询页面大小更新进度。
        返回: {
            "status": "idle" | "scanning" | "updating" | "done" | "cancelled" | "error",
            "total": int,
            "link_queried": int,
            "size_updated": int,
            "failed": int,
            "percent": float,
            "current_page": str,
            "current_files": int,
            "errors": list[str]
        }
        """
        if self._page_size_task is None:
            return {
                "status": "idle",
                "total": 0,
                "link_queried": 0,
                "size_updated": 0,
                "failed": 0,
                "percent": 0.0,
                "current_page": "",
                "current_files": 0,
                "errors": [],
            }
        return self._page_size_task.get_progress()

    def cancel_page_size_update(self):
        """
        取消页面大小更新任务。
        返回: {"status": "cancelled"} 或 {"status": "idle"}
        """
        if self._page_size_task is None:
            return {"status": "idle"}
        result = self._page_size_task.cancel()
        self.logger.info("PageSizeUpdate cancelled by user")
        return result

    def shutdown(self):
        """
        释放资源：线程池/Session
        """
        try:
            self.downloader.shutdown()
        except Exception:
            pass

        if self.Uploader:
            try:
                self.Uploader.shutdown(True)
            except Exception:
                pass



if __name__ == "__main__":
    import os
    import time
    from dotenv import load_dotenv

    load_dotenv()
    token = os.getenv("NOTION_TOKEN", "")
    if not token:
        raise RuntimeError("Please set NOTION_TOKEN env var")

    # ====== 配置区 ======
    page_id = "2fc644ea-d11a-8010-9665-e5fbaba0fd58"
    save_dir = r"C:/Ruibin_Ningh/program/Notion-Files-Management/Notion-Files-Management/downloads"

    # 下载线程数（影响同时下载数量 + probe 并发）
    max_workers = 6

    # probe 轮询打印频率
    probe_print_interval_s = 1.0

    # 下载状态打印频率
    download_print_interval_s = 1.0
    # ====================

    main = Main(notion_token=token, max_workers=max_workers)

    def _fmt_size(x: float) -> str:
        try:
            return f"{float(x):.2f}MB"
        except Exception:
            return "0.00MB"

    try:
        # 1) 发起：获取下载列表 + 启动 size 探测
        ret = main.get_download_list(page_id=page_id)
        print("[get_download_list]", ret)

        probe_id = ret.get("probe_id")
        if not probe_id:
            print("没有可探测的 url（下载列表为空或无 url）。")
            raise SystemExit(0)

        # 2) 轮询：探测进度
        print("\n=== Probing sizes... ===")
        last_print = 0.0
        while True:
            prog = main.download_list_processing(probe_id)
            # prog: {"status","percent","done","total","error"}

            now = time.time()
            if now - last_print >= probe_print_interval_s:
                err = prog.get("error") or {}
                err_count = len(err) if isinstance(err, dict) else 0

                print(
                    f"[probe] status={prog.get('status')} "
                    f"{prog.get('percent', 0.0):.2f}% "
                    f"({prog.get('done', 0)}/{prog.get('total', 0)}) "
                    f"errors={err_count}"
                )

                last_print = now

            if prog.get("status") == "done":
                break

            time.sleep(0.2)

        print("=== Probe done. ===\n")

        # 3) 展示最终列表（带 size_mb）
        print("=== Download list (after probe) ===")
        for i, item in enumerate(main.download_list, 1):
            print(
                f"{i:02d}. {item.get('real_name') or item.get('name')} | "
                f"size={_fmt_size(item.get('size_mb', 0.0))} | "
                f"block_id={item.get('block_id', 'N/A')} | "
                f"url={(item.get('url') or '')[:60]}..."
            )
        print()

        # 4) 启动下载
        print("=== Starting downloads... ===")
        main.download_notion_files(main.download_list, save_directory=save_dir)

        # 5) 轮询下载状态
        print("\n=== Downloading... ===")
        last_print = 0.0
        start = time.time()

        while True:
            statuses = main.get_download_statuses()

            total = len(statuses)
            done = sum(1 for s in statuses if s.get("status") == "completed")
            errn = sum(1 for s in statuses if s.get("status") == "error")
            downloading = sum(1 for s in statuses if s.get("status") == "downloading")
            waiting = sum(1 for s in statuses if s.get("status") == "waiting")
            refreshing = sum(1 for s in statuses if s.get("status") == "refreshing")

            now = time.time()
            if now - last_print >= download_print_interval_s:
                elapsed = int(now - start)
                print(f"[sum] t={elapsed}s total={total} waiting={waiting} downloading={downloading} refreshing={refreshing} done={done} error={errn}")

                # 每个文件一行
                for s in statuses:
                    name = s.get("real_name") or s.get("name") or "unknown"
                    print(
                        f" - {name}: "
                        f"{s.get('status')} "
                        f"{s.get('progress', 0)}% "
                        f"{_fmt_size(s.get('downloaded_mb', 0.0))}/{_fmt_size(s.get('total_mb', 0.0))} "
                        f"spd={s.get('speed_mb_s', 0.0)}MB/s "
                        f"ETA={s.get('ETA', 0)}s "
                        f"err={s.get('error')}"
                    )

                print("-" * 80)
                last_print = now

            # 结束条件：全部完成或错误（且没有正在刷新的）
            if total > 0 and (done + errn) >= total and downloading == 0 and waiting == 0 and refreshing == 0:
                print("\n=== All downloads finished. ===\n")
                break

            time.sleep(0.2)

        # 6) 收尾统计：最快/最慢/失败
        statuses = main.get_download_statuses()
        completed = [s for s in statuses if s.get("status") == "completed"]
        failed = [s for s in statuses if s.get("status") == "error"]

        if completed:
            # 用 usedTime 估计
            completed_sorted = sorted(completed, key=lambda x: x.get("usedTime", 0))
            fastest = completed_sorted[0]
            slowest = completed_sorted[-1]
            print(f"[fastest] {fastest.get('real_name') or fastest.get('name')} usedTime={fastest.get('usedTime')}s")
            print(f"[slowest] {slowest.get('real_name') or slowest.get('name')} usedTime={slowest.get('usedTime')}s")

        if failed:
            print("\n[failed list]")
            for s in failed:
                print(f" - {s.get('real_name') or s.get('name')} err={s.get('error')}")

    except KeyboardInterrupt:
        print("KeyboardInterrupt -> shutdown")
    finally:
        main.shutdown()
        print("shutdown")
