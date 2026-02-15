import urllib.request
import threading
import os
import time
import random
from concurrent.futures import ThreadPoolExecutor
from logger import PythonLogger


class Download:
    def __init__(self, max_workers: int, debug: bool = True):
        self.status_map = {}
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.lock = threading.Lock()
        self.debug = debug

        # ✅ probe 专用：避免探测把下载线程池占满
        self.probe_tasks = {}   # probe_id -> state dict
        self._probe_id_seq = 0
        self.probe_lock = threading.Lock()

    # -------------------------
    # Debug helper
    # -------------------------
    def _dbg(self, method: str, msg: str) -> None:
        if self.debug:
            PythonLogger.debug(f"[{self.__class__.__name__}-{method}] {msg}")

    # =========================
    # Probe: async sizes with progress + retry
    # =========================
    def start_probe_sizes(self, urls: list[str], timeout: float = 10.0, max_retries: int = 3) -> int:
        """
        ✅ 异步启动“探测文件大小”任务，返回 probe_id
        - urls > 10 -> 10 线程
        - urls <=10 -> len(urls) 线程
        - 每个 url 默认重试 3 次（可传 max_retries）
        """
        method = "start_probe_sizes"
        n = len(urls)
        if n == 0:
            raise ValueError("urls is empty")

        workers = 10 if n > 10 else n

        with self.probe_lock:
            self._probe_id_seq += 1
            probe_id = self._probe_id_seq

            state = {
                "probe_id": probe_id,
                "status": "probing",  # probing/done
                "total": n,
                "done": 0,
                "ok": 0,
                "failed": 0,
                "started_mono": time.monotonic(),
                "ended_mono": None,
                "timeout": float(timeout),
                "max_retries": int(max_retries),
                "urls": list(urls),
                "results": {},  # url -> {"size_mb": float|None, "error": str|None, "attempts": int}
                "errors": {},  # ✅ url -> error str
            }
            self.probe_tasks[probe_id] = state

        self._dbg(method, f"probe_id={probe_id} urls={n} workers={workers} retries={max_retries}")

        # ✅ 每次 probe 启动一个短生命周期线程池（只负责这次 probe）
        # 好处：不会长期占用资源，也不会影响下载线程池
        pool = ThreadPoolExecutor(max_workers=workers)

        def _on_done(url: str, size_mb: float | None, err: str | None, attempts: int):
            with self.probe_lock:
                st = self.probe_tasks.get(probe_id)
                if not st:
                    return
                st["results"][url] = {"size_mb": size_mb, "error": err, "attempts": attempts}
                st["done"] += 1
                if size_mb is not None:
                    st["ok"] += 1
                else:
                    st["failed"] += 1
                    if err:
                        st["errors"][url] = err  # ✅ 把错误传出来

                if st["done"] >= st["total"]:
                    st["status"] = "done"
                    st["ended_mono"] = time.monotonic()

        # 提交每个 url 的 probe 任务
        for url in urls:
            fut = pool.submit(self._probe_one_with_retry, url, timeout, max_retries)
            def _cb(f, _url=url):
                try:
                    size_mb, attempts = f.result()
                    _on_done(_url, size_mb, None, attempts)
                except Exception as e:
                    # 理论上 _probe_one_with_retry 不会抛（内部会吞），这里兜底
                    _on_done(_url, None, str(e), max_retries)
            fut.add_done_callback(_cb)

        # probe 全结束后关闭池（不阻塞调用方）
        def _shutdown_pool_when_done():
            # 轮询探测完成
            while True:
                with self.probe_lock:
                    st = self.probe_tasks.get(probe_id)
                    if not st or st["status"] == "done":
                        break
                time.sleep(0.05)
            pool.shutdown(wait=False)

        threading.Thread(target=_shutdown_pool_when_done, daemon=True).start()

        return probe_id

    def get_probe_progress(self, probe_id: int) -> dict:
        """
        ✅ 查询 probe 进度：
        {
          "probe_id": 1,
          "status": "probing"|"done",
          "progress": 0-100,
          "done": x,
          "total": n,
          "ok": x,
          "failed": x,
          "usedTime": seconds,
          "ETA": seconds_or_0
        }
        """
        with self.probe_lock:
            st = self.probe_tasks.get(probe_id)
            if not st:
                return {"probe_id": probe_id, "status": "not_found"}

            total = st["total"]
            done = st["done"]
            ok = st["ok"]
            failed = st["failed"]
            status = st["status"]
            start = st["started_mono"]
            end = st["ended_mono"] or time.monotonic()
            used = max(0.0, end - start)
            progress = (done / total * 100.0) if total else 0.0

            # ETA：按平均完成速率估计
            eta = 0
            if status != "done" and used > 0 and done > 0:
                rate = done / used  # items/sec
                remain = total - done
                eta = int(remain / rate) if rate > 1e-9 else 0

            return {
                "probe_id": probe_id,
                "status": status,
                "progress": round(progress, 2),
                "done": done,
                "total": total,
                "ok": ok,
                "failed": failed,
                "usedTime": int(used),
                "ETA": eta,
                "errors": dict(list(st.get("errors", {}).items())[:10]) if failed > 0 else None,  # ✅ 返回最多 10 条错误
            }

    def get_probe_results(self, probe_id: int, partial: bool = True) -> dict[str, float | None]:
        """
        ✅ 获取 probe 结果：
        返回 {url: size_mb or None}

        partial=True：即使还没完成，也返回当前已有的结果
        partial=False：未完成就返回空 dict
        """
        with self.probe_lock:
            st = self.probe_tasks.get(probe_id)
            if not st:
                return {}

            if (not partial) and st["status"] != "done":
                return {}

            out = {}
            for url, info in st["results"].items():
                out[url] = info.get("size_mb")
            return out

    def _probe_one_with_retry(self, url: str, timeout: float, max_retries: int) -> tuple[float | None, int]:
        """
        ✅ 单个 url 探测，带重试：
        返回 (size_mb or None, attempts_used)
        """
        method = "_probe_one_with_retry"
        last_err = None

        for attempt in range(1, max_retries + 1):
            try:
                size_mb = self._probe_one(url, timeout)
                if size_mb is not None and size_mb > 0:
                    if self.debug:
                        self._dbg(method, f"ok url={url[:60]}... size_mb={size_mb} attempts={attempt}")
                    return size_mb, attempt
                else:
                    last_err = "no_content_length"
                    if self.debug:
                        self._dbg(method, f"miss url={url[:60]}... attempts={attempt}")
            except Exception as e:
                last_err = repr(e)
                if self.debug:
                    self._dbg(method, f"err url={url[:60]}... attempts={attempt} err={e!r}")

            # backoff（最后一次不 sleep）
            if attempt < max_retries:
                self._sleep_backoff(attempt=attempt)

        if self.debug:
            self._dbg(method, f"failed url={url[:60]}... err={last_err}")
        return None, max_retries

    def _sleep_backoff(self, attempt: int) -> None:
        """
        指数退避 + jitter
        attempt 从 1 开始
        """
        base = 0.4
        cap = 3.0
        wait = base * (2 ** (attempt - 1))
        wait += random.uniform(0, 0.15)
        wait = min(wait, cap)
        time.sleep(wait)

    def _probe_one(self, url: str, timeout: float) -> float | None:
        """
        HEAD Content-Length -> Range GET Content-Range
        返回 size_mb 或 None
        """
        size_bytes = self._probe_head_content_length(url, timeout)
        if size_bytes is not None and size_bytes > 0:
            return round(size_bytes / (1024 * 1024), 3)

        size_bytes = self._probe_range_total_size(url, timeout)
        if size_bytes is not None and size_bytes > 0:
            return round(size_bytes / (1024 * 1024), 3)

        return None

    def _probe_head_content_length(self, url: str, timeout: float) -> int | None:
        req = urllib.request.Request(url, method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                cl = resp.headers.get("Content-Length")
                if cl:
                    try:
                        return int(cl)
                    except ValueError:
                        return None
        except Exception:
            return None
        return None

    def _probe_range_total_size(self, url: str, timeout: float) -> int | None:
        req = urllib.request.Request(url, method="GET", headers={"Range": "bytes=0-0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                cr = resp.headers.get("Content-Range")
                # "bytes 0-0/123456789"
                if cr and "/" in cr:
                    tail = cr.split("/")[-1].strip()
                    if tail.isdigit():
                        return int(tail)
        except Exception:
            return None
        return None

    # =========================
    # Download: task
    # =========================
    def download(self, url: str, save_name: str, size: float):
        with self.lock:
            if url in self.status_map and self.status_map[url]["status"] in ["waiting", "downloading", "completed"]:
                return {"msg": "Task already exists", "status": self.status_map[url]["status"]}

            self.status_map[url] = {
                "progress": 0,
                "downloaded_mb": 0.0,
                "total_mb": size,
                "status": "waiting",
                "save_name": save_name,
                "speed_mb_s": 0.0,
                "usedTime": 0,
                "ETA": 0,
                "error": None
            }

        self.executor.submit(self._worker, url, save_name, size)
        return {"msg": "Task submitted", "url": url}

    def _worker(self, url: str, save_name: str, manual_size_mb: float):
        start_mono = time.monotonic()
        last_update_mono = start_mono
        last_downloaded_bytes = 0
        current_speed_bps = 0.0

        with self.lock:
            if url in self.status_map:
                self.status_map[url]["status"] = "downloading"

        def report(block_num, block_size, total_size):
            nonlocal last_update_mono, last_downloaded_bytes, current_speed_bps

            if total_size <= 0:
                total_size = manual_size_mb * 1024 * 1024

            if total_size > 0:
                now = time.monotonic()
                elapsed_since_last = now - last_update_mono

                if elapsed_since_last >= 0.5:
                    downloaded_bytes = min(block_num * block_size, total_size)
                    newly_downloaded = downloaded_bytes - last_downloaded_bytes

                    instant_speed = newly_downloaded / elapsed_since_last if elapsed_since_last > 0 else 0.0
                    current_speed_bps = instant_speed if current_speed_bps == 0 else (current_speed_bps * 0.3 + instant_speed * 0.7)

                    remaining_bytes = total_size - downloaded_bytes
                    eta = int(remaining_bytes / current_speed_bps) if current_speed_bps > 1024 else 0

                    last_update_mono = now
                    last_downloaded_bytes = downloaded_bytes

                    with self.lock:
                        if url in self.status_map:
                            item = self.status_map[url]
                            item["downloaded_mb"] = round(downloaded_bytes / (1024 * 1024), 2)
                            item["total_mb"] = round(total_size / (1024 * 1024), 2)
                            item["progress"] = round((downloaded_bytes / total_size) * 100, 2)
                            item["speed_mb_s"] = round(current_speed_bps / (1024 * 1024), 2)
                            item["usedTime"] = int(now - start_mono)
                            item["ETA"] = eta

        try:
            d = os.path.dirname(save_name)
            if d:
                os.makedirs(d, exist_ok=True)

            urllib.request.urlretrieve(url, save_name, reporthook=report)

            end_mono = time.monotonic()
            with self.lock:
                if url in self.status_map:
                    self.status_map[url].update({
                        "status": "completed",
                        "progress": 100.0,
                        "downloaded_mb": self.status_map[url]["total_mb"],
                        "speed_mb_s": 0.0,
                        "ETA": 0,
                        "usedTime": int(end_mono - start_mono),
                    })

        except Exception as e:
            end_mono = time.monotonic()
            with self.lock:
                if url in self.status_map:
                    self.status_map[url]["status"] = "error"
                    self.status_map[url]["error"] = str(e)
                    self.status_map[url]["usedTime"] = int(end_mono - start_mono)

    def get_status(self, url: str):
        with self.lock:
            return self.status_map.get(url, {"status": "not_found"})

    def shutdown(self, wait: bool = True):
        self.executor.shutdown(wait=wait)


"""
下载类的状态格式:(内部使用)
[
    {
        "progress": 100,  # 0-100
        "downloaded_mb": 20.5,
        "total_mb": 20.5,
        "status": "completed",
        "save_name": "path/to/file.ext",
        "speed_mb_s": 2.5,
        "usedTime": 0,
        "ETA": 0,
        "error": null
    }
]
"""