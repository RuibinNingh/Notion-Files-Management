"""流式扫描一个 Notion 页面的所有可下载文件，边发现边探测大小。
从原 Scripts/main.py 的 start_download_list_streaming 系列方法提取而来，
改为每个扫描任务一个独立实例（隔离 download_list / _scan_status）。
线程安全。
"""
import threading
import queue as _queue
from concurrent.futures import ThreadPoolExecutor

from logger import PythonLogger


class ScanSession:
    def __init__(self, notion, probe_workers: int = 8):
        self.notion = notion
        self.probe_workers = probe_workers
        from download import Download
        self.downloader = Download(max_workers=probe_workers)
        self.download_list: list = []
        self._scan_lock = threading.Lock()
        self._scan_status = {
            "status": "scanning", "discovered": 0, "done": False, "error": None,
            "probe_id": None, "total_urls": 0, "files_probed": 0, "probing_done": False,
        }
        self._probe_id = None
        self._stream_probe_queue: _queue.Queue = _queue.Queue()
        self._scan_cancelled = False

    def start(self, page_id: str):
        """启动后台扫描线程（立即返回）。"""
        self._scan_cancelled = False

        def _probe_consumer():
            pool = ThreadPoolExecutor(max_workers=self.probe_workers)
            futures = []

            def _probe_one(item_ref, url):
                if self._scan_cancelled:
                    return
                size_mb = None
                try:
                    size_mb = self.downloader._probe_one(url, timeout=10)
                except Exception as e:
                    PythonLogger.warning(f"[PROBE] {e!r}, url_tail={url[-60:]!r}")
                item_ref["size_mb"] = size_mb if size_mb is not None else 0.0
                with self._scan_lock:
                    self._scan_status["files_probed"] = self._scan_status.get("files_probed", 0) + 1

            while True:
                if self._scan_cancelled:
                    break
                try:
                    msg = self._stream_probe_queue.get(timeout=0.5)
                except _queue.Empty:
                    with self._scan_lock:
                        if self._scan_status["done"] and self._stream_probe_queue.empty():
                            break
                    continue
                if msg is None:
                    break
                item_ref, url = msg
                futures.append(pool.submit(_probe_one, item_ref, url))

            if self._scan_cancelled:
                for f in futures:
                    f.cancel()
                pool.shutdown(wait=False)
            else:
                for f in futures:
                    try:
                        f.result(timeout=30)
                    except Exception:
                        pass
                pool.shutdown(wait=False)
            with self._scan_lock:
                self._scan_status["probing_done"] = True

        def _worker():
            try:
                self._scan_blocks_streaming(page_id)
                try:
                    page_obj = self.notion.get_page_object(page_id)
                    if page_obj:
                        pf = self.notion.extract_page_level_files(page_obj)
                        if pf:
                            with self._scan_lock:
                                self.download_list.extend(pf)
                                self._scan_status["discovered"] = len(self.download_list)
                            for item in pf:
                                url = item.get("url", "")
                                if url:
                                    self._stream_probe_queue.put((item, url))
                except Exception as e:
                    PythonLogger.warning(f"Page-level files extraction failed (non-fatal): {e}")

                PythonLogger.info(f"Streaming scan completed: {len(self.download_list)} files")
                self._stream_probe_queue.put(None)
                total_urls = sum(1 for f in self.download_list if f.get("url"))
                with self._scan_lock:
                    self._scan_status["total_urls"] = total_urls
                    self._scan_status["status"] = "probing" if total_urls else "done"
                    self._scan_status["done"] = True
            except Exception as e:
                PythonLogger.error(f"Streaming scan failed: {e}")
                with self._scan_lock:
                    self._scan_status.update({"status": "error", "error": str(e), "done": True})
                self._stream_probe_queue.put(None)

        threading.Thread(target=_probe_consumer, daemon=True).start()
        threading.Thread(target=_worker, daemon=True).start()
        return {"status": "scanning", "msg": "开始流式扫描页面文件"}

    def _scan_blocks_streaming(self, page_id: str):
        blocks = self.notion.query_page(page_id, fetch_all=False)
        files = self.notion.get_download_url_no_recurse(blocks)
        if files:
            with self._scan_lock:
                self.download_list.extend(files)
                self._scan_status["discovered"] = len(self.download_list)
            for item in files:
                url = item.get("url", "")
                if url:
                    self._stream_probe_queue.put((item, url))
        for block in blocks:
            if self._scan_cancelled:
                return
            if block.get("has_children"):
                self._scan_blocks_streaming(block["id"])

    def get_status(self):
        with self._scan_lock:
            return dict(self._scan_status)

    def cancel(self):
        self._scan_cancelled = True
        try:
            self._stream_probe_queue.put_nowait(None)
        except Exception:
            pass
        PythonLogger.info("[SCAN] cancel called")

    def read_list(self):
        with self._scan_lock:
            return [dict(it) for it in self.download_list]

    def shutdown(self):
        try:
            self.downloader.shutdown()
        except Exception:
            pass
