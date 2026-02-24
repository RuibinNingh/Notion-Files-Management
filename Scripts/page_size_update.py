"""
page_size_update.py — Notion 页面大小自动更新 (v1.5.1-Status, streaming 优化)

功能:
    扫描数据源中选定页面的所有文件块（含子页面递归），
    计算总文件大小（GB），自动将累加结果写回到用户指定的数字属性。

架构 (v1.5.1-Status 流式优化):
    流式 URL 发现 + 即时大小探测 + 按页面聚合更新
    - 链接查询线程池 (link_workers):
        递归查询页面 blocks（含 child_page / child_database），
        **发现一个文件 URL 就立即推入大小探测队列**，避免 URL 过期。
    - 大小查询线程池 (size_workers):
        即时 HTTP HEAD/Range 探测文件大小（无速率限制），
        按页面累加，当某页面全部 URL 探测完毕后自动更新属性。
    - 按页面聚合器 (_PageAccumulator):
        线程安全地追踪每个页面已发现的 URL 数、已探测数、累计大小，
        以及块扫描是否完成，确保属性更新时机正确。
    - 全局 Notion API 速率限制器:
        确保所有 Notion API 调用合计不超过 3 req/s。

变更说明 (相比 v1.4.0-Status):
    - 新增 _PageAccumulator 内部类，按页面追踪流式探测进度
    - _query_page_files 改为流式：发现 URL 立即推入 _size_queue
    - _scan_blocks_streaming 新增 child_page/child_database 递归展开
    - _size_worker_pool 改为消费 (accumulator, url) 单条消息
    - 新增 files_discovered / files_probed 进度字段
    - 进度百分比算法改为 (size_updated + failed) / total
    - 失败 URL 增加重试（最多 2 次）
"""

import threading
import time
import queue
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from logger import PythonLogger
from notion import Notion


class PageSizeUpdateTask:
    """
    页面大小自动更新任务（流式优化版）。

    用法:
        task = PageSizeUpdateTask(notion, ds_id, size_prop, page_ids, link_workers=3, size_workers=5)
        task.start()
        task.get_progress()
        task.cancel()
    """

    # Notion API 速率限制: 3 req/s → 每次请求间隔至少 0.34s
    _NOTION_API_INTERVAL = 0.34

    # 可下载的媒体块类型 (与 notion.py MEDIA_BLOCK_TYPES 保持一致)
    _MEDIA_BLOCK_TYPES = frozenset({"file", "image", "pdf", "audio", "video"})

    class _PageAccumulator:
        """
        线程安全的按页面聚合器。
        追踪单个页面的 URL 发现数、探测完成数、累计大小、扫描完成状态。
        """
        __slots__ = (
            "page_id", "page_title", "lock",
            "total_urls", "probed_count", "total_size_gb",
            "scan_done", "_update_done",
        )

        def __init__(self, page_id: str, page_title: str):
            self.page_id = page_id
            self.page_title = page_title
            self.lock = threading.Lock()
            self.total_urls = 0
            self.probed_count = 0
            self.total_size_gb = 0.0
            self.scan_done = False
            self._update_done = False

        def add_url(self):
            """链接查询线程调用：记录发现一个新 URL。"""
            with self.lock:
                self.total_urls += 1

        def add_size(self, size_gb: float):
            """大小探测线程调用：记录一个 URL 探测完成。"""
            with self.lock:
                self.probed_count += 1
                self.total_size_gb += size_gb

        def mark_scan_done(self):
            """链接查询线程调用：该页面的块扫描已全部完成。"""
            with self.lock:
                self.scan_done = True

        def is_ready_for_update(self) -> bool:
            """
            检查是否可以更新页面属性：
            扫描完成 AND 所有发现的 URL 都已探测 AND 尚未更新过。
            """
            with self.lock:
                if self._update_done:
                    return False
                if self.scan_done and self.probed_count >= self.total_urls:
                    self._update_done = True
                    return True
                return False

        def get_final_size(self) -> float:
            with self.lock:
                return round(self.total_size_gb, 3)

    def __init__(
        self,
        notion: Notion,
        data_source_id: str,
        size_property_name: str,
        page_ids: list[str],
        link_workers: int = 3,
        size_workers: int = 5,
    ):
        self.notion = notion
        self.data_source_id = data_source_id
        self.size_property_name = size_property_name
        self.page_ids = list(page_ids)
        self.link_workers = min(max(link_workers, 1), 8)
        self.size_workers = min(max(size_workers, 1), 16)

        # 进度跟踪
        self._lock = threading.Lock()
        self._total = len(page_ids)
        self._link_queried = 0       # 已完成链接查询的页面数
        self._size_updated = 0       # 已成功更新大小的页面数
        self._failed = 0             # 失败的页面数
        self._files_discovered = 0   # 流式发现的文件 URL 总数
        self._files_probed = 0       # 已完成大小探测的文件数
        self._errors: list[str] = []
        self._status = "idle"        # idle | scanning | updating | done | cancelled | error
        self._cancel_event = threading.Event()
        self._thread: threading.Thread | None = None

        # 当前进度明细 (用于前端显示)
        self._current_page_title = ""
        self._current_page_files = 0

        # 全局 Notion API 速率限制器 (链接查询 + 属性更新 共享)
        self._api_rate_lock = threading.Lock()
        self._last_api_time = 0.0

        # 流式消息队列: (_PageAccumulator, url: str) 或 None (结束信号)
        self._size_queue: queue.Queue = queue.Queue()

        # 所有页面的聚合器
        self._accumulators: list["PageSizeUpdateTask._PageAccumulator"] = []

    def start(self) -> dict:
        if self._status in ("scanning", "updating"):
            return {"status": "error", "error": "已有页面大小更新任务正在运行"}

        self._reset()
        self._status = "scanning"
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="PageSizeUpdateTask"
        )
        self._thread.start()
        return {"status": "started"}

    def cancel(self) -> dict:
        self._cancel_event.set()
        self._status = "cancelled"
        PythonLogger.info("[PageSizeUpdate] 任务已取消")
        return {"status": "cancelled"}

    def get_progress(self) -> dict:
        with self._lock:
            return {
                "status": self._status,
                "total": self._total,
                "link_queried": self._link_queried,
                "size_updated": self._size_updated,
                "failed": self._failed,
                "files_discovered": self._files_discovered,
                "files_probed": self._files_probed,
                "percent": self._calc_percent(),
                "current_page": self._current_page_title,
                "current_files": self._current_page_files,
                "errors": list(self._errors[-20:]),
            }

    # =========================================================================
    # 内部实现
    # =========================================================================

    def _reset(self):
        with self._lock:
            self._total = len(self.page_ids)
            self._link_queried = 0
            self._size_updated = 0
            self._failed = 0
            self._files_discovered = 0
            self._files_probed = 0
            self._errors.clear()
            self._status = "idle"
            self._current_page_title = ""
            self._current_page_files = 0
        self._cancel_event.clear()
        self._last_api_time = 0.0
        self._accumulators.clear()
        # 清空队列
        while not self._size_queue.empty():
            try:
                self._size_queue.get_nowait()
            except queue.Empty:
                break

    def _calc_percent(self) -> float:
        """进度百分比 = 已完成页面（更新成功 + 失败）/ 总页面数。"""
        if self._total <= 0:
            return 0.0
        done_pages = self._size_updated + self._failed
        return round(min((done_pages / self._total) * 100.0, 100.0), 1)

    def _notion_api_wait(self):
        """全局 Notion API 速率限制等待。所有 Notion API 调用前必须调用此方法。"""
        with self._api_rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_api_time
            if elapsed < self._NOTION_API_INTERVAL:
                time.sleep(self._NOTION_API_INTERVAL - elapsed)
            self._last_api_time = time.monotonic()

    def _set_error(self, msg: str):
        PythonLogger.error(f"[PageSizeUpdate] {msg}")
        with self._lock:
            self._status = "error"
            self._errors.append(msg)

    def _run(self):
        """主流程: 启动链接查询线程池和大小查询线程池并发运行（流式）。"""
        try:
            PythonLogger.info(
                f"[PageSizeUpdate] 开始 (streaming): ds={self.data_source_id}, "
                f"size_prop={self.size_property_name}, "
                f"pages={self._total}, link_workers={self.link_workers}, "
                f"size_workers={self.size_workers}"
            )

            if not self.page_ids:
                with self._lock:
                    self._status = "done"
                return

            # 启动大小探测线程池 (消费者)
            size_pool_done = threading.Event()
            size_thread = threading.Thread(
                target=self._size_worker_pool,
                args=(size_pool_done,),
                daemon=True,
                name="SizeWorkerPool",
            )
            size_thread.start()

            # 链接查询线程池 (生产者) — 流式推送
            with self._lock:
                self._status = "scanning"

            with ThreadPoolExecutor(
                max_workers=self.link_workers, thread_name_prefix="LinkQuery"
            ) as link_pool:
                futures = {}
                for page_id in self.page_ids:
                    if self._cancel_event.is_set():
                        break
                    future = link_pool.submit(self._query_page_files_streaming, page_id)
                    futures[future] = page_id

                for future in as_completed(futures):
                    if self._cancel_event.is_set():
                        break
                    page_id = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        with self._lock:
                            self._link_queried += 1
                            self._failed += 1
                            self._errors.append(
                                f"链接查询失败 ({page_id[:8]}...): {str(e)[:100]}"
                            )
                        PythonLogger.error(
                            f"[PageSizeUpdate] 链接查询失败: page_id={page_id}, error={e}"
                        )

            # 链接查询全部完成，发送结束信号
            self._size_queue.put(None)

            # 等待大小探测线程池完成
            size_pool_done.wait()

            if not self._cancel_event.is_set():
                with self._lock:
                    self._status = "done"
                PythonLogger.info(
                    f"[PageSizeUpdate] 完成: updated={self._size_updated}, "
                    f"failed={self._failed}, files_discovered={self._files_discovered}, "
                    f"files_probed={self._files_probed}"
                )

        except Exception as e:
            self._set_error(f"任务异常: {str(e)}")

    def _query_page_files_streaming(self, page_id: str):
        """
        流式查询单个页面的所有文件块（含子页面递归），
        发现一个文件 URL 就立即推入 _size_queue。

        使用 Notion API，受全局速率限制。
        """
        if self._cancel_event.is_set():
            return

        # 创建该页面的聚合器
        page_title = page_id[:8]  # fallback
        acc = self._PageAccumulator(page_id, page_title)
        self._accumulators.append(acc)

        with self._lock:
            self._current_page_title = page_title
            self._current_page_files = 0

        try:
            # 递归查询 blocks，流式推送 URL
            self._notion_api_wait()
            self._scan_blocks_streaming(page_id, acc)
        except Exception as e:
            PythonLogger.error(
                f"[PageSizeUpdate] 流式扫描异常: page_id={page_id}, error={e}"
            )
            with self._lock:
                self._errors.append(
                    f"扫描异常 ({page_id[:8]}...): {str(e)[:100]}"
                )

        # 标记该页面扫描完成
        acc.mark_scan_done()

        with self._lock:
            self._link_queried += 1

        # 如果该页面没有发现任何文件，直接更新为 0
        if acc.total_urls == 0:
            if acc.is_ready_for_update():
                self._update_page_size(page_id, acc.page_title, 0.0)

        PythonLogger.info(
            f"[PageSizeUpdate] 页面 {page_id[:8]}... 扫描完成, "
            f"发现 {acc.total_urls} 个文件"
        )

    def _scan_blocks_streaming(self, block_id: str, acc: "_PageAccumulator"):
        """
        递归查询 block 的所有子块，发现文件 URL 立即推入队列。
        支持 child_page / child_database 递归展开。
        """
        cursor = None
        max_retries = 4

        while True:
            if self._cancel_event.is_set():
                return

            params = {}
            if cursor:
                params["start_cursor"] = cursor

            # 速率限制 (第一次调用已在外部限制)
            if cursor:
                self._notion_api_wait()

            data = None
            for attempt in range(max_retries):
                try:
                    res = requests.get(
                        f"{self.notion.url}/blocks/{block_id}/children",
                        headers=self.notion.default_headers,
                        params=params,
                        timeout=15,
                    )

                    if res.status_code in [429, 500, 502, 503, 504]:
                        wait_time = 2 ** attempt
                        PythonLogger.warning(
                            f"[PageSizeUpdate] blocks 查询限制({res.status_code})，"
                            f"等待 {wait_time}s..."
                        )
                        time.sleep(wait_time)
                        continue

                    res.raise_for_status()
                    data = res.json()
                    break

                except Exception as e:
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                    else:
                        PythonLogger.error(
                            f"[PageSizeUpdate] blocks 查询失败: {block_id}, {e}"
                        )
                        return

            if data is None:
                return

            blocks = data.get("results", [])

            for block in blocks:
                if self._cancel_event.is_set():
                    return

                block_type = block.get("type")

                # 提取文件 URL 并立即推入队列
                if block_type in self._MEDIA_BLOCK_TYPES:
                    url = self._extract_url_from_block(block, block_type)
                    if url:
                        acc.add_url()
                        with self._lock:
                            self._files_discovered += 1
                            self._current_page_files = acc.total_urls
                        self._size_queue.put((acc, url))

                # 递归处理有子块的 blocks（包括 child_page / child_database）
                if block.get("has_children"):
                    child_id = block["id"]
                    self._notion_api_wait()
                    self._scan_blocks_streaming(child_id, acc)

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

    @staticmethod
    def _extract_url_from_block(block: dict, block_type: str) -> str | None:
        """从单个媒体块中提取文件 URL。"""
        media_info = block.get(block_type, {})
        hosting_type = media_info.get("type")

        if hosting_type == "file":
            return media_info.get("file", {}).get("url")
        elif hosting_type == "external":
            return media_info.get("external", {}).get("url")
        return None

    def _size_worker_pool(self, done_event: threading.Event):
        """
        大小探测线程池: 消费 (accumulator, url) 消息，
        逐个探测文件大小，累加到聚合器。
        当某页面全部探测完毕且扫描已结束时，自动更新页面属性。
        """
        try:
            with ThreadPoolExecutor(
                max_workers=self.size_workers, thread_name_prefix="SizeProbe"
            ) as pool:
                futures = {}

                while True:
                    if self._cancel_event.is_set():
                        break

                    try:
                        item = self._size_queue.get(timeout=0.5)
                    except queue.Empty:
                        continue

                    if item is None:
                        # 生产者已全部结束
                        break

                    acc, url = item
                    future = pool.submit(self._probe_single_url, acc, url)
                    futures[future] = (acc, url)

                # 等待所有进行中的 size 任务完成
                for future in as_completed(futures):
                    if self._cancel_event.is_set():
                        break
                    acc, url = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        PythonLogger.error(
                            f"[PageSizeUpdate] 探测异常: {url[:60]}..., {e}"
                        )

        except Exception as e:
            self._set_error(f"大小探测池异常: {str(e)}")
        finally:
            done_event.set()

    def _probe_single_url(self, acc: "_PageAccumulator", url: str):
        """
        探测单个文件 URL 大小，结果累加到聚合器。
        探测完成后检查是否可以更新页面属性。
        """
        if self._cancel_event.is_set():
            return

        size_gb = self._probe_file_size(url)
        acc.add_size(size_gb)

        with self._lock:
            self._files_probed += 1

        # 检查该页面是否全部探测完毕
        if acc.is_ready_for_update():
            final_size = acc.get_final_size()
            self._update_page_size(acc.page_id, acc.page_title, final_size)

    @staticmethod
    def _probe_file_size(url: str, max_retries: int = 2) -> float:
        """
        探测单个文件大小 (GB)。无 Notion API 速率限制。
        策略: HEAD Content-Length → Range GET Content-Range（与 download.py 一致）
        失败时重试（最多 max_retries 次）。
        """
        for attempt in range(max_retries + 1):
            # 策略 1: HEAD 请求获取 Content-Length
            size_bytes = PageSizeUpdateTask._probe_head_content_length(url)
            if size_bytes is not None and size_bytes > 0:
                return size_bytes / (1024 * 1024 * 1024)

            # 策略 2: Range GET 请求解析 Content-Range
            size_bytes = PageSizeUpdateTask._probe_range_total_size(url)
            if size_bytes is not None and size_bytes > 0:
                return size_bytes / (1024 * 1024 * 1024)

            if attempt < max_retries:
                time.sleep(1.0 * (attempt + 1))

        PythonLogger.warning(
            f"[PageSizeUpdate] 无法获取文件大小 (HEAD+Range 均失败): {url[:80]}..."
        )
        return 0.0

    @staticmethod
    def _probe_head_content_length(url: str, timeout: float = 10) -> int | None:
        """HEAD 请求获取 Content-Length，返回字节数或 None。"""
        try:
            response = requests.head(url, allow_redirects=True, timeout=timeout)
            # 检查 URL 过期 (401/403/410)
            if response.status_code in (401, 403, 410):
                return None
            cl = response.headers.get("content-length")
            if cl:
                try:
                    return int(cl)
                except ValueError:
                    return None
        except Exception:
            pass
        return None

    @staticmethod
    def _probe_range_total_size(url: str, timeout: float = 10) -> int | None:
        """Range GET (bytes=0-0) 解析 Content-Range 获取总大小，返回字节数或 None。"""
        try:
            response = requests.get(
                url,
                headers={"Range": "bytes=0-0"},
                allow_redirects=True,
                timeout=timeout,
                stream=True,
            )
            # 检查 URL 过期
            if response.status_code in (401, 403, 410):
                response.close()
                return None
            cr = response.headers.get("content-range")
            # 格式: "bytes 0-0/123456789"
            if cr and "/" in cr:
                tail = cr.split("/")[-1].strip()
                if tail.isdigit():
                    response.close()
                    return int(tail)
            # 关闭连接，避免资源泄漏
            response.close()
        except Exception:
            pass
        return None

    def _update_page_size(self, page_id: str, page_title: str, size_gb: float):
        """更新单个页面的大小属性。使用 Notion API，受速率限制。"""
        if self._cancel_event.is_set():
            return

        self._notion_api_wait()

        properties = {
            self.size_property_name: {
                "number": round(size_gb, 3),
            }
        }

        try:
            self.notion.update_page_properties(page_id, properties)
            with self._lock:
                self._size_updated += 1
            PythonLogger.info(
                f"[PageSizeUpdate] 更新成功: {page_title[:30]} = {size_gb:.3f} GB"
            )
        except Exception as e:
            with self._lock:
                self._failed += 1
                self._errors.append(
                    f"属性更新失败 {page_title[:20]}... ({page_id[:8]}): "
                    f"{str(e)[:100]}"
                )
            PythonLogger.error(
                f"[PageSizeUpdate] 属性更新失败: {page_id}, {e}"
            )


def scan_pages_for_size_property(
    notion: Notion, data_source_id: str, size_property_name: str
) -> dict:
    """
    扫描数据源所有页面，按大小属性是否已设置分类。

    返回:
    {
        "status": "success" | "error",
        "pages_with_size": [{"id": "...", "title": "...", "size_value": 123.45}, ...],
        "pages_without_size": [{"id": "...", "title": "..."}, ...],
        "total": int,
        "error": "..."
    }
    """
    try:
        PythonLogger.info(
            f"[ScanPages] 开始扫描数据源 {data_source_id}，大小属性={size_property_name}"
        )

        pages = notion.query_database(data_source_id)
        PythonLogger.info(f"[ScanPages] 查询到 {len(pages)} 个页面")

        pages_with_size = []
        pages_without_size = []

        # 查找 title 属性名
        title_prop = None
        if pages:
            first_page_props = pages[0].get("properties", {})
            for prop_name, prop_val in first_page_props.items():
                if prop_val.get("type") == "title":
                    title_prop = prop_name
                    break

        for page in pages:
            page_id = page.get("id", "")
            props = page.get("properties", {})

            # 提取标题
            title_text = ""
            if title_prop:
                title_obj = props.get(title_prop, {})
                title_arr = title_obj.get("title", [])
                title_text = "".join(
                    t.get("plain_text", "") for t in title_arr
                ).strip()

            if not title_text:
                title_text = page_id[:12] + "..."

            # 检查大小属性
            size_obj = props.get(size_property_name, {})
            size_value = size_obj.get("number")

            if size_value is not None:
                pages_with_size.append({
                    "id": page_id,
                    "title": title_text,
                    "size_value": round(float(size_value), 3),
                })
            else:
                pages_without_size.append({
                    "id": page_id,
                    "title": title_text,
                })

        PythonLogger.info(
            f"[ScanPages] 分类完成: 已设置={len(pages_with_size)}, "
            f"未设置={len(pages_without_size)}"
        )

        return {
            "status": "success",
            "pages_with_size": pages_with_size,
            "pages_without_size": pages_without_size,
            "total": len(pages),
        }

    except Exception as e:
        PythonLogger.error(f"[ScanPages] 扫描失败: {e}")
        return {
            "status": "error",
            "pages_with_size": [],
            "pages_without_size": [],
            "total": 0,
            "error": str(e),
        }
