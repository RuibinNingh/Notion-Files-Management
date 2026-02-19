"""
migrate.py — 数据源属性同步模块 (v1.3.1-Status.1)

方案:
    用户先在 Notion 中手动复制源数据库页面并粘贴到目标数据库（保留 blocks 和文件），
    然后用本工具按属性映射将源页面的属性值同步到目标数据库中对应的页面。

匹配逻辑: 通过页面标题 (title) 匹配源页面和目标页面。
架构:     MigrationTask 使用 ThreadPoolExecutor 实现多线程并发，内置速率限制。
"""
import threading
import time
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from logger import PythonLogger
from notion import Notion


class MigrationTask:
    """
    属性同步任务。

    前提: 用户已在 Notion 中手动将源数据库页面复制粘贴到目标数据库。
    功能: 按属性映射，将源页面的属性值同步到目标页面。

    用法:
        task = MigrationTask(notion, src_id, tgt_id, mapping, workers=2)
        task.start()
        task.get_progress()
        task.cancel()
    """

    _RATE_LIMIT_INTERVAL = 0.4  # Notion API 速率限制安全间隔

    def __init__(self, notion: Notion, source_id: str, target_id: str,
                 property_mapping: dict, max_workers: int = 3):
        self.notion = notion
        self.source_id = source_id
        self.target_id = target_id
        self.property_mapping = property_mapping  # {src_prop: tgt_prop}
        self.max_workers = min(max_workers, 2)

        # 进度跟踪
        self._lock = threading.Lock()
        self._total = 0
        self._done = 0
        self._failed = 0
        self._errors: list[str] = []
        self._status = "idle"  # idle | querying | migrating | done | cancelled | error
        self._cancel_event = threading.Event()
        self._thread: threading.Thread | None = None

        # 速率限制
        self._rate_lock = threading.Lock()
        self._last_request_time = 0.0

        # 属性 Schema
        self._src_prop_types: dict[str, str] = {}
        self._tgt_prop_types: dict[str, str] = {}

    def start(self) -> dict:
        if self._status in ("querying", "migrating"):
            return {"status": "error", "error": "同步任务已在运行中"}

        self._reset()
        self._status = "querying"
        self._thread = threading.Thread(target=self._run, daemon=True, name="MigrationTask")
        self._thread.start()
        return {"status": "started"}

    def cancel(self) -> dict:
        self._cancel_event.set()
        self._status = "cancelled"
        PythonLogger.info("[MigrationTask] 同步任务已取消")
        return {"status": "cancelled"}

    def get_progress(self) -> dict:
        with self._lock:
            total = self._total
            done = self._done
            failed = self._failed
            errors = list(self._errors[-20:])
            status = self._status

        percent = 0.0
        if total > 0:
            percent = round((done + failed) / total * 100, 1)

        return {
            "status": status,
            "total": total,
            "done": done,
            "failed": failed,
            "percent": percent,
            "errors": errors,
        }

    # =========================================================================
    # 内部实现
    # =========================================================================

    def _reset(self):
        with self._lock:
            self._total = 0
            self._done = 0
            self._failed = 0
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

    def _run(self):
        """同步主流程。"""
        try:
            PythonLogger.info(f"[MigrationTask] 开始属性同步: {self.source_id} -> {self.target_id}")
            PythonLogger.info(f"[MigrationTask] 属性映射: {self.property_mapping}")

            # 1. 获取源和目标的属性 Schema
            src_info = self.notion.get_database_properties(self.source_id)
            if src_info.get("status") != "success":
                self._set_error(f"获取源数据源属性失败: {src_info.get('error', '未知错误')}")
                return

            tgt_info = self.notion.get_database_properties(self.target_id)
            if tgt_info.get("status") != "success":
                self._set_error(f"获取目标数据源属性失败: {tgt_info.get('error', '未知错误')}")
                return

            self._src_prop_types = {name: p["type"] for name, p in src_info["properties"].items()}
            self._tgt_prop_types = {name: p["type"] for name, p in tgt_info["properties"].items()}

            # 找到 title 属性名
            src_title_prop = self._find_title_prop(self._src_prop_types)
            tgt_title_prop = self._find_title_prop(self._tgt_prop_types)

            if not src_title_prop or not tgt_title_prop:
                self._set_error("无法找到源或目标数据源的标题属性")
                return

            if self._cancel_event.is_set():
                return

            # 2. 查询源和目标的所有页面
            self._status = "querying"
            PythonLogger.info("[MigrationTask] 正在查询源数据源页面...")
            src_pages = self.notion.query_database(self.source_id)

            if self._cancel_event.is_set():
                return

            PythonLogger.info("[MigrationTask] 正在查询目标数据源页面...")
            tgt_pages = self.notion.query_database(self.target_id)

            if self._cancel_event.is_set():
                return

            # 3. 按标题建立目标页面索引 {title: page}
            #    如有同名页面，保留最新创建的
            tgt_index: dict[str, dict] = {}
            for page in tgt_pages:
                title = self._extract_title(page, tgt_title_prop)
                if not title:
                    continue
                existing = tgt_index.get(title)
                if existing is None:
                    tgt_index[title] = page
                else:
                    if page.get("created_time", "") > existing.get("created_time", ""):
                        tgt_index[title] = page

            PythonLogger.info(f"[MigrationTask] 源页面: {len(src_pages)}, 目标页面: {len(tgt_pages)}, 目标索引: {len(tgt_index)}")

            # 4. 匹配源页面 -> 目标页面
            matched_pairs = []  # [(src_page, tgt_page), ...]
            unmatched = []

            for src_page in src_pages:
                src_title = self._extract_title(src_page, src_title_prop)
                if not src_title:
                    unmatched.append(src_page.get("id", "unknown"))
                    continue

                tgt_page = tgt_index.get(src_title)
                if tgt_page:
                    matched_pairs.append((src_page, tgt_page))
                else:
                    unmatched.append(f"{src_title} ({src_page.get('id', '')})")

            if unmatched:
                PythonLogger.warning(f"[MigrationTask] {len(unmatched)} 个源页面未匹配到目标: {unmatched[:5]}...")

            with self._lock:
                self._total = len(matched_pairs)

            if self._total == 0:
                msg = f"没有匹配到任何页面（源 {len(src_pages)} 个，目标 {len(tgt_pages)} 个）。请确认已在 Notion 中将源页面复制粘贴到目标数据库。"
                PythonLogger.warning(f"[MigrationTask] {msg}")
                self._set_error(msg)
                return

            PythonLogger.info(f"[MigrationTask] 匹配到 {self._total} 对页面，开始同步属性...")
            self._status = "migrating"

            # 5. 多线程同步属性
            with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="sync") as executor:
                futures = {}
                for src_page, tgt_page in matched_pairs:
                    if self._cancel_event.is_set():
                        break
                    future = executor.submit(self._sync_one_page, src_page, tgt_page)
                    futures[future] = src_page.get("id", "unknown")

                for future in as_completed(futures):
                    if self._cancel_event.is_set():
                        for f in futures:
                            f.cancel()
                        break

                    page_id = futures[future]
                    try:
                        future.result()
                        with self._lock:
                            self._done += 1
                    except Exception as e:
                        with self._lock:
                            self._failed += 1
                            self._errors.append(f"页面 {page_id}: {str(e)}")
                        PythonLogger.error(f"[MigrationTask] 页面 {page_id} 同步失败: {e}")

            if not self._cancel_event.is_set():
                self._status = "done"
                PythonLogger.info(f"[MigrationTask] 同步完成: 成功={self._done}, 失败={self._failed}, 未匹配={len(unmatched)}")

        except Exception as e:
            self._set_error(f"同步异常: {str(e)}")
            PythonLogger.error(f"[MigrationTask] 同步异常: {e}")

    def _set_error(self, msg: str):
        with self._lock:
            self._status = "error"
            self._errors.append(msg)

    def _find_title_prop(self, prop_types: dict[str, str]) -> str | None:
        """找到 title 类型的属性名。"""
        for name, ptype in prop_types.items():
            if ptype == "title":
                return name
        return None

    def _extract_title(self, page: dict, title_prop_name: str) -> str:
        """从页面对象中提取标题文本。"""
        props = page.get("properties", {})
        title_prop = props.get(title_prop_name, {})
        title_items = title_prop.get("title", [])
        return "".join(t.get("plain_text", "") for t in title_items).strip()

    def _sync_one_page(self, src_page: dict, tgt_page: dict):
        """
        同步单个页面的属性:
        从源页面读取属性值，按映射写入目标页面。
        跳过 title 属性（已通过复制粘贴保留）和只读属性。
        """
        src_id = src_page.get("id", "")
        tgt_id = tgt_page.get("id", "")

        if self._cancel_event.is_set():
            return

        # 转换属性
        src_properties = src_page.get("properties", {})
        new_properties = self._convert_properties(src_properties)

        if not new_properties:
            PythonLogger.info(f"[MigrationTask] 页面 {src_id} -> {tgt_id} 无需更新属性")
            return

        # 更新目标页面属性
        self._rate_limit_wait()
        self.notion.update_page_properties(tgt_id, new_properties)
        PythonLogger.info(f"[MigrationTask] 页面 {src_id} -> {tgt_id} 属性同步成功 ({len(new_properties)} 个)")

    def _convert_properties(self, src_properties: dict) -> dict:
        """
        按属性映射转换属性值。
        跳过只读属性和 title 属性。
        """
        new_props = {}

        for src_name, tgt_name in self.property_mapping.items():
            if src_name not in src_properties:
                continue

            src_type = self._src_prop_types.get(src_name, "")

            # 跳过只读属性
            if src_type in Notion.READONLY_PROPERTY_TYPES:
                PythonLogger.info(f"[MigrationTask] 跳过只读属性: {src_name} (type={src_type})")
                continue

            # 跳过 title（复制粘贴已保留）
            if src_type == "title":
                PythonLogger.info(f"[MigrationTask] 跳过标题属性: {src_name}（已通过复制保留）")
                continue

            # 检查目标属性是否只读
            tgt_type = self._tgt_prop_types.get(tgt_name, "")
            if tgt_type in Notion.READONLY_PROPERTY_TYPES:
                PythonLogger.info(f"[MigrationTask] 跳过目标只读属性: {tgt_name} (type={tgt_type})")
                continue

            src_value = src_properties[src_name]
            new_props[tgt_name] = self._clean_property_value(src_value)

        return new_props

    def _clean_property_value(self, prop_value: dict) -> dict:
        """深拷贝属性值，清理不可写字段。"""
        copied = copy.deepcopy(prop_value)
        copied.pop("id", None)

        prop_type = copied.get("type", "")

        if prop_type == "multi_select":
            for item in copied.get("multi_select", []):
                item.pop("id", None)
                item.pop("description", None)
                item.pop("color", None)
        elif prop_type == "select":
            sel = copied.get("select")
            if sel:
                sel.pop("id", None)
                sel.pop("description", None)
                sel.pop("color", None)
        elif prop_type == "status":
            st = copied.get("status")
            if st:
                st.pop("id", None)
                st.pop("description", None)
                st.pop("color", None)
        elif prop_type == "relation":
            for item in copied.get("relation", []):
                keys_to_remove = [k for k in item if k != "id"]
                for k in keys_to_remove:
                    item.pop(k, None)
        elif prop_type == "people":
            for item in copied.get("people", []):
                keys_to_remove = [k for k in item if k not in ("object", "id")]
                for k in keys_to_remove:
                    item.pop(k, None)
        elif prop_type == "date":
            dt = copied.get("date")
            if dt:
                dt.pop("id", None)
        elif prop_type == "rich_text":
            for item in copied.get("rich_text", []):
                item.pop("href", None)
                ann = item.get("annotations")
                if ann:
                    ann.pop("id", None)
        elif prop_type == "files":
            cleaned = []
            for item in copied.get("files", []):
                if item.get("type") == "file":
                    # Notion 内部文件无法写入，跳过
                    continue
                cleaned.append(item)
            copied["files"] = cleaned

        return copied
