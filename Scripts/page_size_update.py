"""
page_size_update.py — Notion 页面大小自动更新 (v1.4.0-Status)

功能:
    扫描数据源中选定页面的所有文件块，计算总文件大小（GB），
    自动将累加结果写回到用户指定的数字属性。

架构:
    双线程池模型 + 全局 Notion API 速率限制器
    - 链接查询线程池 (link_workers):
        通过 Notion API 递归查询页面 blocks → 提取文件 URL
        受 Notion 3 req/s 速率限制
    - 大小查询线程池 (size_workers):
        HTTP HEAD 获取文件大小（无速率限制） + 更新页面属性（受 3 req/s 限制）
    - 全局 Notion API 速率限制器:
        确保所有 Notion API 调用（链接查询 + 属性更新）合计不超过 3 req/s
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
    页面大小自动更新任务。

    用法:
        task = PageSizeUpdateTask(notion, ds_id, size_prop, page_ids, link_workers=3, size_workers=5)
        task.start()
        task.get_progress()
        task.cancel()
    """

    # Notion API 速率限制: 3 req/s → 每次请求间隔至少 0.34s
    _NOTION_API_INTERVAL = 0.34

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

        # 链接查询结果队列: (page_id, page_title, file_urls: list[str])
        self._size_queue: queue.Queue = queue.Queue()

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
            self._errors.clear()
            self._status = "idle"
            self._current_page_title = ""
            self._current_page_files = 0
        self._cancel_event.clear()
        self._last_api_time = 0.0
        # 清空队列
        while not self._size_queue.empty():
            try:
                self._size_queue.get_nowait()
            except queue.Empty:
                break

    def _calc_percent(self) -> float:
        if self._total <= 0:
            return 0.0
        # 链接查询占 40%，大小更新占 60%
        link_pct = (self._link_queried / self._total) * 40.0
        update_pct = ((self._size_updated + self._failed) / self._total) * 60.0
        return round(min(link_pct + update_pct, 100.0), 1)

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
        """主流程: 启动链接查询线程池和大小查询线程池并发运行。"""
        try:
            PythonLogger.info(
                f"[PageSizeUpdate] 开始: ds={self.data_source_id}, "
                f"size_prop={self.size_property_name}, "
                f"pages={self._total}, link_workers={self.link_workers}, "
                f"size_workers={self.size_workers}"
            )

            if not self.page_ids:
                with self._lock:
                    self._status = "done"
                return

            # 启动大小查询线程池 (消费者)
            size_pool_done = threading.Event()
            size_thread = threading.Thread(
                target=self._size_worker_pool,
                args=(size_pool_done,),
                daemon=True,
                name="SizeWorkerPool",
            )
            size_thread.start()

            # 链接查询线程池 (生产者)
            with self._lock:
                self._status = "scanning"

            with ThreadPoolExecutor(
                max_workers=self.link_workers, thread_name_prefix="LinkQuery"
            ) as link_pool:
                futures = {}
                for page_id in self.page_ids:
                    if self._cancel_event.is_set():
                        break
                    future = link_pool.submit(self._query_page_files, page_id)
                    futures[future] = page_id

                for future in as_completed(futures):
                    if self._cancel_event.is_set():
                        break
                    page_id = futures[future]
                    try:
                        page_title, file_urls = future.result()
                        with self._lock:
                            self._link_queried += 1
                        # 放入大小查询队列
                        self._size_queue.put((page_id, page_title, file_urls))
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

            # 等待大小查询线程池完成
            size_pool_done.wait()

            if not self._cancel_event.is_set():
                with self._lock:
                    self._status = "done"
                PythonLogger.info(
                    f"[PageSizeUpdate] 完成: updated={self._size_updated}, "
                    f"failed={self._failed}"
                )

        except Exception as e:
            self._set_error(f"任务异常: {str(e)}")

    def _query_page_files(self, page_id: str) -> tuple[str, list[str]]:
        """
        查询单个页面的所有文件块，提取文件 URL。
        使用 Notion API，受全局速率限制。

        返回: (page_title, file_urls)
        """
        if self._cancel_event.is_set():
            return "", []

        # 获取页面信息以获取标题
        page_title = page_id[:8]  # fallback

        # 使用 Notion API 查询页面 blocks (递归)
        self._notion_api_wait()
        blocks = self._query_page_blocks_recursive(page_id)

        # 从 blocks 中提取文件 URL
        file_urls = self._extract_file_urls(blocks)

        PythonLogger.info(
            f"[PageSizeUpdate] 页面 {page_id[:8]}... 找到 {len(file_urls)} 个文件"
        )

        return page_title, file_urls

    def _query_page_blocks_recursive(self, page_id: str) -> list:
        """
        递归查询页面所有 blocks。每次分页调用都经过速率限制。
        """
        all_blocks = []
        cursor = None
        max_retries = 4

        while True:
            if self._cancel_event.is_set():
                return all_blocks

            params = {}
            if cursor:
                params["start_cursor"] = cursor

            # 速率限制 (除了第一次调用已在外部限制)
            if cursor:
                self._notion_api_wait()

            for attempt in range(max_retries):
                try:
                    res = requests.get(
                        f"{self.notion.url}/blocks/{page_id}/children",
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
                    break

                except Exception as e:
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                    else:
                        PythonLogger.error(
                            f"[PageSizeUpdate] blocks 查询失败: {page_id}, {e}"
                        )
                        return all_blocks

            data = res.json()
            blocks = data.get("results", [])

            # 递归处理有子块的 blocks
            for block in blocks:
                if block.get("has_children"):
                    self._notion_api_wait()
                    block["children"] = self._query_page_blocks_recursive(block["id"])

            all_blocks.extend(blocks)

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        return all_blocks

    @staticmethod
    def _extract_file_urls(blocks: list) -> list[str]:
        """从 blocks 列表中递归提取所有文件 URL。"""
        urls = []
        for block in blocks:
            if block.get("type") == "file":
                file_info = block.get("file", {})
                if file_info.get("type") == "file":
                    url = file_info.get("file", {}).get("url")
                elif file_info.get("type") == "external":
                    url = file_info.get("external", {}).get("url")
                else:
                    url = None
                if url:
                    urls.append(url)

            # 递归处理子块
            if "children" in block:
                urls.extend(PageSizeUpdateTask._extract_file_urls(block["children"]))

        return urls

    def _size_worker_pool(self, done_event: threading.Event):
        """
        大小查询线程池: 消费链接查询结果队列，
        对每个页面的文件做 HEAD 请求获取大小，然后更新属性。
        """
        try:
            with self._lock:
                if self._status == "scanning":
                    pass  # 保持 scanning 直到链接查询完成

            with ThreadPoolExecutor(
                max_workers=self.size_workers, thread_name_prefix="SizeQuery"
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
                        # 生产者已结束
                        break

                    page_id, page_title, file_urls = item

                    if not file_urls:
                        # 没有文件的页面，大小为 0
                        future = pool.submit(
                            self._update_page_size, page_id, page_title, 0.0
                        )
                    else:
                        future = pool.submit(
                            self._probe_and_update, page_id, page_title, file_urls
                        )
                    futures[future] = (page_id, page_title)

                # 等待所有 size 任务完成
                for future in as_completed(futures):
                    if self._cancel_event.is_set():
                        break
                    page_id, page_title = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        with self._lock:
                            self._failed += 1
                            self._errors.append(
                                f"更新失败 {page_title[:20]}... ({page_id[:8]}): "
                                f"{str(e)[:100]}"
                            )
                        PythonLogger.error(
                            f"[PageSizeUpdate] 更新失败: {page_id}, {e}"
                        )

        except Exception as e:
            self._set_error(f"大小查询池异常: {str(e)}")
        finally:
            done_event.set()

    def _probe_and_update(self, page_id: str, page_title: str, file_urls: list[str]):
        """
        对单个页面: 探测所有文件大小 → 累加 → 更新属性。
        HEAD 请求无速率限制，可以并行。属性更新受 Notion API 速率限制。
        """
        if self._cancel_event.is_set():
            return

        with self._lock:
            self._current_page_title = page_title or page_id[:8]
            self._current_page_files = len(file_urls)

        # 逐个 HEAD 请求获取文件大小 (无速率限制)
        total_size_gb = 0.0
        for url in file_urls:
            if self._cancel_event.is_set():
                return
            size = self._probe_file_size(url)
            total_size_gb += size

        total_size_gb = round(total_size_gb, 3)

        # 更新页面属性 (Notion API, 受速率限制)
        self._update_page_size(page_id, page_title, total_size_gb)

    @staticmethod
    def _probe_file_size(url: str) -> float:
        """HEAD 请求获取单个文件大小 (GB)。无速率限制。"""
        try:
            response = requests.head(url, allow_redirects=True, timeout=10)
            size_bytes = response.headers.get("content-length")
            if size_bytes:
                return int(size_bytes) / (1024 * 1024 * 1024)
        except Exception as e:
            PythonLogger.warning(f"[PageSizeUpdate] HEAD 获取大小失败: {e}")
        return 0.0

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
