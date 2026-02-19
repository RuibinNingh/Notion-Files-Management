"""
batch_rename.py — 批量去除数据库页面标题后缀 (v1.3.0-Status)

功能: 查询数据源中所有页面，对标题中包含用户指定后缀的页面，
      去除该后缀并更新页面标题。

架构: BatchRemoveSuffixTask 使用 ThreadPoolExecutor 实现多线程并发，
      内置速率限制，与 MigrationTask 保持一致的进度汇报接口。
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from logger import PythonLogger
from notion import Notion


class BatchRemoveSuffixTask:
    """
    批量去除页面标题后缀任务。

    用法:
        task = BatchRemoveSuffixTask(notion, data_source_id, suffix, workers=2)
        task.start()
        task.get_progress()
        task.cancel()
    """

    _RATE_LIMIT_INTERVAL = 0.4  # Notion API 速率限制安全间隔

    def __init__(self, notion: Notion, data_source_id: str,
                 suffix: str, max_workers: int = 3):
        self.notion = notion
        self.data_source_id = data_source_id
        self.suffix = suffix
        self.max_workers = min(max(max_workers, 1), 4)  # 限制 1-4

        # 进度跟踪
        self._lock = threading.Lock()
        self._total = 0        # 匹配到后缀的页面总数
        self._scanned = 0      # 已扫描的页面总数
        self._done = 0         # 成功去除后缀的页面数
        self._failed = 0       # 失败的页面数
        self._skipped = 0      # 不含后缀的页面数（跳过）
        self._errors: list[str] = []
        self._status = "idle"  # idle | querying | processing | done | cancelled | error
        self._cancel_event = threading.Event()
        self._thread: threading.Thread | None = None

        # 速率限制
        self._rate_lock = threading.Lock()
        self._last_request_time = 0.0

    def start(self) -> dict:
        if self._status in ("querying", "processing"):
            return {"status": "error", "error": "任务已在运行中"}

        self._reset()
        self._status = "querying"
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="BatchRemoveSuffixTask"
        )
        self._thread.start()
        return {"status": "started"}

    def cancel(self) -> dict:
        self._cancel_event.set()
        self._status = "cancelled"
        PythonLogger.info("[BatchRemoveSuffix] 任务已取消")
        return {"status": "cancelled"}

    def get_progress(self) -> dict:
        with self._lock:
            total = self._total
            scanned = self._scanned
            done = self._done
            failed = self._failed
            skipped = self._skipped
            errors = list(self._errors[-20:])
            status = self._status

        percent = 0.0
        if total > 0:
            percent = round((done + failed) / total * 100, 1)

        return {
            "status": status,
            "total": total,
            "scanned": scanned,
            "done": done,
            "failed": failed,
            "skipped": skipped,
            "percent": percent,
            "errors": errors,
        }

    # =========================================================================
    # 内部实现
    # =========================================================================

    def _reset(self):
        with self._lock:
            self._total = 0
            self._scanned = 0
            self._done = 0
            self._failed = 0
            self._skipped = 0
            self._errors.clear()
            self._status = "idle"
        self._cancel_event.clear()
        self._last_request_time = 0.0

    def _rate_limit_wait(self):
        with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._RATE_LIMIT_INTERVAL:
                time.sleep(self._RATE_LIMIT_INTERVAL - elapsed)
            self._last_request_time = time.monotonic()

    def _set_error(self, msg: str):
        PythonLogger.error(f"[BatchRemoveSuffix] {msg}")
        with self._lock:
            self._status = "error"
            self._errors.append(msg)

    def _run(self):
        """主流程。"""
        try:
            PythonLogger.info(
                f"[BatchRemoveSuffix] 开始: data_source={self.data_source_id}, "
                f"suffix='{self.suffix}', workers={self.max_workers}"
            )

            # 1. 获取数据源属性 Schema，找到 title 属性名
            ds_info = self.notion.get_database_properties(self.data_source_id)
            if ds_info.get("status") != "success":
                self._set_error(f"获取数据源属性失败: {ds_info.get('error', '未知错误')}")
                return

            prop_types = {name: p["type"] for name, p in ds_info["properties"].items()}
            title_prop = self._find_title_prop(prop_types)
            if not title_prop:
                self._set_error("无法找到数据源的标题 (title) 属性")
                return

            if self._cancel_event.is_set():
                return

            # 2. 查询所有页面
            PythonLogger.info("[BatchRemoveSuffix] 正在查询数据源页面...")
            pages = self.notion.query_database(self.data_source_id)

            if self._cancel_event.is_set():
                return

            with self._lock:
                self._scanned = len(pages)

            PythonLogger.info(f"[BatchRemoveSuffix] 查询到 {len(pages)} 个页面")

            # 3. 筛选标题包含后缀的页面
            matched_pages = []  # [(page_id, old_title, new_title, title_prop_name)]
            for page in pages:
                title_text = self._extract_title(page, title_prop)
                if title_text and title_text.endswith(self.suffix):
                    new_title = title_text[: -len(self.suffix)].rstrip()  # 去除后缀并 trim 右侧空格
                    if new_title:  # 确保去除后缀后标题不为空
                        matched_pages.append((
                            page.get("id", ""),
                            title_text,
                            new_title,
                            title_prop,
                        ))

            with self._lock:
                self._total = len(matched_pages)
                self._skipped = len(pages) - len(matched_pages)

            PythonLogger.info(
                f"[BatchRemoveSuffix] 匹配到 {len(matched_pages)} 个页面含后缀 '{self.suffix}'，"
                f"跳过 {self._skipped} 个"
            )

            if not matched_pages:
                with self._lock:
                    self._status = "done"
                PythonLogger.info("[BatchRemoveSuffix] 没有需要处理的页面，任务完成")
                return

            # 4. 多线程更新
            self._status = "processing"
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                futures = {}
                for page_id, old_title, new_title, tp in matched_pages:
                    if self._cancel_event.is_set():
                        break
                    future = pool.submit(
                        self._update_page_title,
                        page_id, old_title, new_title, tp
                    )
                    futures[future] = (page_id, old_title)

                for future in as_completed(futures):
                    if self._cancel_event.is_set():
                        break
                    page_id, old_title = futures[future]
                    try:
                        future.result()
                        with self._lock:
                            self._done += 1
                    except Exception as e:
                        with self._lock:
                            self._failed += 1
                            self._errors.append(
                                f"页面 {old_title[:30]}... ({page_id[:8]}): {str(e)[:100]}"
                            )
                        PythonLogger.error(
                            f"[BatchRemoveSuffix] 更新失败: page_id={page_id}, error={e}"
                        )

            if not self._cancel_event.is_set():
                with self._lock:
                    self._status = "done"
                PythonLogger.info(
                    f"[BatchRemoveSuffix] 完成: done={self._done}, "
                    f"failed={self._failed}, skipped={self._skipped}"
                )

        except Exception as e:
            self._set_error(f"任务异常: {str(e)}")

    def _update_page_title(self, page_id: str, old_title: str, new_title: str,
                           title_prop_name: str):
        """更新单个页面的标题属性。"""
        self._rate_limit_wait()

        if self._cancel_event.is_set():
            return

        properties = {
            title_prop_name: {
                "title": [
                    {
                        "type": "text",
                        "text": {"content": new_title},
                    }
                ]
            }
        }

        self.notion.update_page_properties(page_id, properties)
        PythonLogger.info(
            f"[BatchRemoveSuffix] 更新成功: '{old_title}' -> '{new_title}'"
        )

    @staticmethod
    def _find_title_prop(prop_types: dict) -> str | None:
        """在属性 Schema 中找到 type=title 的属性名。"""
        for name, ptype in prop_types.items():
            if ptype == "title":
                return name
        return None

    @staticmethod
    def _extract_title(page: dict, title_prop_name: str) -> str:
        """从页面对象中提取标题文本。"""
        try:
            props = page.get("properties", {})
            title_obj = props.get(title_prop_name, {})
            title_arr = title_obj.get("title", [])
            return "".join(t.get("plain_text", "") for t in title_arr).strip()
        except Exception:
            return ""
