"""Notion 业务 facade：构造 Notion 客户端 + 按任务隔离的 Download/Upload/ScanSession。
替代原 Scripts/main.py 的 Main 类（去掉全局 download_list 状态，改为每任务独立实例）。
叶子模块 notion/download/upload/migrate/batch_rename/page_size_update 基本未改动。
"""
import os
import threading
import time
from collections import defaultdict

from .config import config
from .taskregistry import registry, TaskHandle
from .staging import new_task_dir, write_cache_meta

from notion import Notion
from download import Download
from upload import Upload
from migrate import MigrationTask
from batch_rename import BatchRemoveSuffixTask
from page_size_update import PageSizeUpdateTask, scan_pages_for_size_property
from scan import ScanSession
from logger import PythonLogger


class NotionFacade:
    def __init__(self):
        self._lock = threading.Lock()
        self._notion = None
        self._token = None
        self._url = None

    def _ensure_notion(self) -> Notion:
        token = config["notion_token"]
        url = (config["notion_base_url"] or "https://api.notion.com/v1").rstrip("/")
        with self._lock:
            if self._notion and self._token == token and self._url == url:
                return self._notion
            if not token:
                raise RuntimeError("未配置 Notion Token，请先在【设置】页保存 Token。")
            self._notion = Notion(token, url=url)
            self._token = token
            self._url = url
            PythonLogger.info(f"Notion client ready (url={url})")
            return self._notion

    # -------- 同步辅助（一次性返回） --------
    def get_database_properties(self, ds_id):
        return self._ensure_notion().get_database_properties(ds_id)

    def scan_pages_for_size_property(self, ds_id, size_prop):
        return scan_pages_for_size_property(self._ensure_notion(), ds_id, size_prop)

    # -------- 扫描任务 --------
    def start_scan(self, page_id, probe_workers=8) -> TaskHandle:
        notion = self._ensure_notion()
        session = ScanSession(notion, probe_workers=probe_workers)
        session.start(page_id)

        def poll():
            st = session.get_status()
            st["done"] = bool(st.get("done") and st.get("probing_done"))
            if st["done"] and st.get("status") != "error":
                st["status"] = "done"
                st["percent"] = 100
            elif st.get("total_urls"):
                st["percent"] = min(99, round((st.get("files_probed", 0) / st.get("total_urls", 1)) * 100))
            else:
                st["percent"] = 0
            st["items_count"] = len(session.read_list())
            return st

        return registry.create(
            "scan",
            title="扫描页面文件",
            source="download",
            backend_obj=session,
            poll_fn=poll,
            cancel_fn=session.cancel,
            input={"page_id": page_id, "probe_workers": probe_workers},
            retry_fn=lambda: self.start_scan(page_id, probe_workers),
            retryable=True,
        )

    def read_scan_list(self, tid):
        h = registry.get(tid)
        if not h or h.kind != "scan":
            return []
        return h.backend_obj.read_list()

    # -------- 下载任务（每任务独立 Download 实例 + 任务私有 download_list） --------
    def start_download(self, items, save_dir=None) -> TaskHandle:
        notion = self._ensure_notion()
        dl = Download(
            max_workers=config["max_download_workers"],
            enable_range_download=config["enable_range_download"],
            range_min_mb=config["range_download_min_mb"],
            range_chunks=config["range_download_chunks"],
        )
        if save_dir is None:
            save_dir = new_task_dir("download")
        os.makedirs(save_dir, exist_ok=True)
        meta = {}
        raw_items = [dict(it) for it in items]
        used_names: dict[str, int] = {}
        for it in raw_items:
            url = it.get("url", "")
            if not url:
                continue
            display = it.get("real_name") or it.get("name") or "file"
            base = os.path.basename(display) or "file"
            # 去重：同名文件追加 (n) 后缀，避免互相覆盖
            if base in used_names:
                used_names[base] += 1
                stem, dot, ext = base.rpartition(".")
                unique = f"{stem} ({used_names[base]}){dot}{ext}" if dot else f"{base} ({used_names[base]})"
            else:
                used_names[base] = 0
                unique = base
            save_path = os.path.join(save_dir, unique)
            size_mb = it.get("size_mb", 0.0) or 0.0
            block_id = it.get("block_id", "")
            refresh_cb = None
            if block_id:
                refresh_cb = lambda b=block_id: (notion.refresh_file_url(b) or {}).get("url")
            dl.download(url, save_path, size=size_mb,
                        url_refresh_callback=refresh_cb, max_url_refresh=2)
            meta[url] = {"real_name": display, "save_name": unique, "url": url}
        keys = list(meta.keys())
        display_names = [m.get("real_name") or m.get("save_name") or "file" for m in meta.values()]
        if display_names:
            first_name = os.path.basename(str(display_names[0])) or "file"
            display_name = f"下载 {first_name}" if len(display_names) == 1 else f"下载 {len(display_names)} 个文件 · {first_name}"
            write_cache_meta(save_dir, kind="download", display_name=display_name)

        task_started_at = time.time()
        last_perf_log_at = {"t": 0.0}

        def poll():
            out = []
            for u in keys:
                s = dl.get_status(u)
                m = meta.get(u, {})
                submitted_at = s.get("submitted_at")
                started_at = s.get("started_at")
                out.append({
                    "url": u,
                    "real_name": m.get("real_name"),
                    "save_name": m.get("save_name"),
                    "status": s.get("status", "not_found"),
                    "progress": s.get("progress", 0),
                    "downloaded_mb": s.get("downloaded_mb", 0.0),
                    "total_mb": s.get("total_mb", 0.0),
                    "speed_mb_s": s.get("speed_mb_s", 0.0),
                    "ETA": s.get("ETA", 0),
                    "usedTime": s.get("usedTime", 0),
                    "wait_time_s": int(started_at - submitted_at) if submitted_at and started_at else 0,
                    "mode": s.get("mode", "single"),
                    "range_supported": s.get("range_supported"),
                    "range_chunks": s.get("range_chunks", 0),
                    "range_reason": s.get("range_reason"),
                    "error": s.get("error"),
                })
            active = [x for x in out if x["status"] in ("waiting", "downloading", "refreshing")]
            downloading = [x for x in out if x["status"] in ("downloading", "refreshing")]
            waiting = [x for x in out if x["status"] == "waiting"]
            completed = [x for x in out if x["status"] == "completed"]
            failed = [x for x in out if x["status"] == "error" or x.get("error")]
            downloaded_mb = sum(float(x.get("downloaded_mb") or 0) for x in out)
            total_mb = sum(float(x.get("total_mb") or 0) for x in out)
            speed_mb_s = sum(float(x.get("speed_mb_s") or 0) for x in downloading)
            elapsed_s = max(0, int(time.time() - task_started_at))
            avg_speed_mb_s = round(downloaded_mb / elapsed_s, 3) if elapsed_s > 0 else 0.0
            done = len(out) > 0 and len(active) == 0
            perf = {
                "max_workers": config["max_download_workers"],
                "total_files": len(out),
                "waiting_files": len(waiting),
                "active_files": len(downloading),
                "completed_files": len(completed),
                "failed_files": len(failed),
                "downloaded_mb": round(downloaded_mb, 2),
                "total_mb": round(total_mb, 2),
                "speed_mb_s": round(speed_mb_s, 3),
                "avg_speed_mb_s": avg_speed_mb_s,
                "elapsed_s": elapsed_s,
                "queue_pressure": len(waiting) > 0 and len(downloading) >= config["max_download_workers"],
            }
            now = time.time()
            if done or now - last_perf_log_at["t"] >= 30:
                last_perf_log_at["t"] = now
                slow = [
                    f"{os.path.basename(str(x.get('real_name') or x.get('save_name') or 'file'))}"
                    f" {round(float(x.get('speed_mb_s') or 0), 3)}MB/s"
                    f" {round(float(x.get('progress') or 0), 1)}%"
                    for x in downloading[:3]
                ]
                PythonLogger.info(
                    "[DownloadPerf] "
                    f"files={perf['completed_files']}/{perf['total_files']} "
                    f"active={perf['active_files']}/{perf['max_workers']} "
                    f"waiting={perf['waiting_files']} failed={perf['failed_files']} "
                    f"speed_mb_s={perf['speed_mb_s']} avg_mb_s={perf['avg_speed_mb_s']} "
                    f"downloaded_mb={perf['downloaded_mb']}/{perf['total_mb']} "
                    f"elapsed_s={perf['elapsed_s']} "
                    f"queue_pressure={perf['queue_pressure']} "
                    f"active_files={'; '.join(slow) if slow else '-'}"
                )
            return {
                "status": "done" if done else "running",
                "done": done,
                "items": out,
                "perf": perf,
            }

        def cancel():
            try:
                dl.shutdown(wait=False)
            except Exception:
                pass

        h = registry.create(
            "download",
            title=f"下载 {len(keys)} 个文件",
            source="download",
            backend_obj=dl,
            poll_fn=poll,
            cancel_fn=cancel,
            input={"items": raw_items},
            retry_fn=lambda: self.start_download(raw_items, new_task_dir("download")),
            retryable=True,
            cache_refs=[save_dir],
            meta={"dir": save_dir},
        )
        h.artifact = {
            "cache_id": os.path.basename(save_dir),
            "zip_url": f"/api/download/{h.task_id}/zip",
        }
        return h

    # -------- 上传任务（每任务独立 Upload 实例，status_map 按 file_path 隔离） --------
    def start_upload(self, page_id, file_paths, folder_mode=False, manifest=None) -> TaskHandle:
        notion = self._ensure_notion()
        up = Upload(
            notion_token=config["notion_token"],
            max_workers=config["max_upload_workers"],
            rps=3.0, burst=4, part_size_bytes=15 * 1024 * 1024, debug=True,
            url=(config["notion_base_url"] or "https://api.notion.com/v1").rstrip("/"),
        )
        state = {"scan_done": False}
        if folder_mode and manifest:
            def run_folder():
                try:
                    _upload_tree(up, notion, page_id, manifest)
                finally:
                    state["scan_done"] = True
            threading.Thread(target=run_folder, daemon=True).start()
        else:
            for fp in file_paths:
                up.upload_file(fp, page_id)
            state["scan_done"] = True

        def poll():
            statuses = up.list_status()
            active = [s for s in statuses if s.get("status") in ("waiting", "uploading")]
            done = state["scan_done"] and len(statuses) > 0 and len(active) == 0
            return {"status": "done" if done else "running", "done": done, "items": statuses}

        def cancel():
            try:
                up.shutdown(False)
            except Exception:
                pass

        paths_for_retry = [m["path"] for m in manifest] if folder_mode and manifest else list(file_paths)
        cache_refs = []
        if paths_for_retry:
            parents = [os.path.dirname(p) for p in paths_for_retry]
            try:
                cache_refs = [os.path.commonpath(parents)]
            except ValueError:
                cache_refs = []

        def retry_upload():
            missing = [p for p in paths_for_retry if not os.path.exists(p)]
            if missing:
                raise RuntimeError("上传缓存已不存在，请重新选择文件。")
            retry_manifest = [dict(m) for m in manifest] if manifest else None
            return self.start_upload(page_id, list(file_paths), folder_mode=folder_mode, manifest=retry_manifest)

        return registry.create(
            "upload",
            title=f"上传 {len(paths_for_retry)} 个文件",
            source="upload",
            backend_obj=up,
            poll_fn=poll,
            cancel_fn=cancel,
            input={
                "page_id": page_id,
                "folder_mode": folder_mode,
                "file_count": len(paths_for_retry),
            },
            retry_fn=retry_upload,
            retryable=True,
            cache_refs=cache_refs,
            artifact={"cache_id": os.path.basename(cache_refs[0])} if cache_refs else {},
        )

    # -------- 工具箱任务（每实例设计，直接 new） --------
    def start_migration(self, source_id, target_id, mapping, max_workers):
        notion = self._ensure_notion()
        t = MigrationTask(notion, source_id, target_id, mapping, max_workers)
        t.start()

        def poll():
            p = t.get_progress()
            p["done"] = p.get("status") in ("done", "cancelled", "error")
            return p

        return registry.create("migrate", backend_obj=t, poll_fn=poll, cancel_fn=t.cancel)

    def start_batch_remove_suffix(self, ds_id, suffix, max_workers):
        notion = self._ensure_notion()
        t = BatchRemoveSuffixTask(notion, ds_id, suffix, max_workers)
        t.start()

        def poll():
            p = t.get_progress()
            p["done"] = p.get("status") in ("done", "cancelled", "error")
            return p

        return registry.create("suffix", backend_obj=t, poll_fn=poll, cancel_fn=t.cancel)

    def start_page_size_update(self, ds_id, size_prop, page_ids, link_workers, size_workers):
        notion = self._ensure_notion()
        t = PageSizeUpdateTask(notion, ds_id, size_prop, page_ids, link_workers, size_workers)
        t.start()

        def poll():
            p = t.get_progress()
            p["done"] = p.get("status") in ("done", "cancelled", "error")
            return p

        return registry.create("page-size", backend_obj=t, poll_fn=poll, cancel_fn=t.cancel)


def _upload_tree(up, notion, parent_page_id, manifest):
    """manifest: [{path, rel}]，rel 用 '/' 分隔。为子目录递归创建子页面后上传文件。"""
    dirs: dict[str, list] = defaultdict(list)
    for m in manifest:
        rel = m["rel"]
        parts = rel.split("/")
        d = "/".join(parts[:-1])
        dirs[d].append(m)

    dir_page = {"": parent_page_id}
    for d in sorted(dirs.keys()):
        if d == "":
            continue
        parts = d.split("/")
        cur = parent_page_id
        for i, name in enumerate(parts):
            key = "/".join(parts[: i + 1])
            if key in dir_page:
                cur = dir_page[key]
                continue
            child = notion.create_child_page(cur, name)
            cur = child.get("id", "")
            dir_page[key] = cur

    for d, files in dirs.items():
        target = dir_page.get(d, parent_page_id)
        for m in files:
            try:
                up.upload_file(m["path"], target)
            except Exception as e:
                PythonLogger.error(f"upload {m['rel']} failed: {e}")


facade = NotionFacade()
