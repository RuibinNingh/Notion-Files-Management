import urllib.request
import urllib.error
import threading
import os
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from logger import PythonLogger


# HTTP 状态码：表示链接过期或无权访问（需要刷新 URL）
_EXPIRED_HTTP_CODES = {401, 403, 410}


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


class Download:
    def __init__(self, max_workers: int, debug: bool = True,
                 enable_range_download: bool = False,
                 range_min_mb: int = 128,
                 range_chunks: int = 4):
        self.status_map = {}
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.lock = threading.Lock()
        self.debug = debug
        self.enable_range_download = _coerce_bool(enable_range_download)
        self.range_min_mb = max(1, int(range_min_mb or 128))
        self.range_chunks = max(1, min(16, int(range_chunks or 4)))

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
        ✅ 异步启动"探测文件大小"任务，返回 probe_id
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
                if not st or st["status"] == "cancelled":
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
            # 轮询探测完成或取消
            while True:
                with self.probe_lock:
                    st = self.probe_tasks.get(probe_id)
                    if not st or st["status"] in ("done", "cancelled"):
                        break
                time.sleep(0.05)
            pool.shutdown(wait=False)

        threading.Thread(target=_shutdown_pool_when_done, daemon=True).start()

        return probe_id

    def cancel_probe(self, probe_id: int) -> bool:
        """
        取消指定 probe 任务：标记为 cancelled，让正在运行的线程尽快退出。
        返回 True 表示找到了对应的 probe 并标记成功。
        """
        with self.probe_lock:
            st = self.probe_tasks.get(probe_id)
            if not st:
                return False
            st["status"] = "cancelled"
            st["ended_mono"] = time.monotonic()
            self._dbg("cancel_probe", f"probe_id={probe_id} cancelled")
            return True

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
    def download(self, url: str, save_name: str, size: float,
                 url_refresh_callback=None, max_url_refresh: int = 2):
        """
        提交下载任务。
        
        url_refresh_callback: 可选回调函数，签名 () -> str|None
            当下载因链接过期（HTTP 401/403/410）失败时，调用此回调获取新 URL。
            返回新 URL 字符串，或 None 表示无法刷新。
        max_url_refresh: 最大 URL 刷新次数（默认 2 次）
        """
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
                "error": None,
                "submitted_at": time.time(),
                "started_at": None,
                "first_progress_at": None,
                "completed_at": None,
                "mode": "single",
                "range_supported": None,
                "range_chunks": 0,
                "range_reason": None,
            }

        self.executor.submit(self._worker, url, save_name, size,
                             url_refresh_callback, max_url_refresh)
        return {"msg": "Task submitted", "url": url}

    def _worker(self, url: str, save_name: str, manual_size_mb: float,
                url_refresh_callback=None, max_url_refresh: int = 2):
        """
        下载工作线程。
        支持链接过期自动刷新：当遇到 HTTP 401/403/410 时，
        通过 url_refresh_callback 获取新 URL 并重试下载。
        """
        current_url = url
        refresh_count = 0

        while True:
            success, is_expired = self._do_download(current_url, url, save_name, manual_size_mb)

            if success:
                return  # 下载完成

            if not is_expired:
                return  # 非过期错误，不重试

            # 链接过期，尝试刷新
            if url_refresh_callback is None:
                PythonLogger.warning(f"[Download] URL 过期但无刷新回调: {current_url[:80]}...")
                return

            if refresh_count >= max_url_refresh:
                PythonLogger.error(f"[Download] URL 刷新次数已达上限({max_url_refresh}): {current_url[:80]}...")
                with self.lock:
                    if url in self.status_map:
                        self.status_map[url]["error"] = f"链接过期，已重试刷新 {max_url_refresh} 次仍失败"
                return

            refresh_count += 1
            PythonLogger.info(f"[Download] 链接过期，尝试刷新 URL (第 {refresh_count}/{max_url_refresh} 次)...")

            # 更新状态为"刷新中"
            with self.lock:
                if url in self.status_map:
                    self.status_map[url]["status"] = "refreshing"
                    self.status_map[url]["error"] = None

            try:
                new_url = url_refresh_callback()
            except Exception as e:
                PythonLogger.error(f"[Download] URL 刷新回调异常: {e}")
                with self.lock:
                    if url in self.status_map:
                        self.status_map[url]["status"] = "error"
                        self.status_map[url]["error"] = f"刷新链接失败: {e}"
                return

            if not new_url:
                PythonLogger.error("[Download] URL 刷新回调返回空")
                with self.lock:
                    if url in self.status_map:
                        self.status_map[url]["status"] = "error"
                        self.status_map[url]["error"] = "刷新链接失败（回调返回空）"
                return

            PythonLogger.info(f"[Download] URL 已刷新，重新下载: {new_url[:80]}...")
            current_url = new_url

            # 重置下载状态，准备重新下载
            with self.lock:
                if url in self.status_map:
                    self.status_map[url].update({
                        "status": "downloading",
                        "progress": 0,
                        "downloaded_mb": 0.0,
                        "speed_mb_s": 0.0,
                        "ETA": 0,
                        "error": None,
                    })

            # 删除之前可能下载了一部分的文件
            self._cleanup_download_files(save_name)

    def _do_download(self, current_url: str, original_url: str,
                     save_name: str, manual_size_mb: float) -> tuple[bool, bool]:
        """
        执行一次实际下载。
        
        返回: (success: bool, is_expired: bool)
        - success=True: 下载成功
        - success=False, is_expired=True: 因链接过期失败（可重试）
        - success=False, is_expired=False: 因其他原因失败（不可重试）
        """
        start_mono = time.monotonic()
        last_update_mono = start_mono
        last_downloaded_bytes = 0
        current_speed_bps = 0.0

        with self.lock:
            if original_url in self.status_map:
                self.status_map[original_url]["status"] = "downloading"
                if not self.status_map[original_url].get("started_at"):
                    self.status_map[original_url]["started_at"] = time.time()
        PythonLogger.info(
            f"[Download] start file={os.path.basename(save_name)!r} "
            f"manual_size_mb={round(manual_size_mb or 0, 2)}"
        )

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
                        if original_url in self.status_map:
                            item = self.status_map[original_url]
                            if not item.get("first_progress_at"):
                                item["first_progress_at"] = time.time()
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

            range_outcome, range_expired, range_reason = self._maybe_range_download(
                current_url=current_url,
                original_url=original_url,
                save_name=save_name,
                manual_size_mb=manual_size_mb,
                start_mono=start_mono,
            )
            if range_outcome == "completed":
                return True, False
            if range_outcome == "failed":
                return False, range_expired
            if range_outcome == "fallback":
                if range_reason != "disabled":
                    PythonLogger.info(
                        f"[DownloadRange] fallback file={os.path.basename(save_name)!r} "
                        f"reason={range_reason}"
                    )

            urllib.request.urlretrieve(current_url, save_name, reporthook=report)

            end_mono = time.monotonic()
            with self.lock:
                total_mb = self.status_map[original_url]["total_mb"] if original_url in self.status_map else manual_size_mb
                if (not total_mb) and os.path.exists(save_name):
                    total_mb = round(os.path.getsize(save_name) / (1024 * 1024), 2)
                if original_url in self.status_map:
                    self.status_map[original_url].update({
                        "status": "completed",
                        "progress": 100.0,
                        "downloaded_mb": total_mb,
                        "total_mb": total_mb,
                        "speed_mb_s": 0.0,
                        "ETA": 0,
                        "usedTime": int(end_mono - start_mono),
                        "completed_at": time.time(),
                    })
            used = max(0.001, end_mono - start_mono)
            avg_speed = (float(total_mb or 0) / used) if total_mb else 0.0
            PythonLogger.info(
                f"[Download] completed file={os.path.basename(save_name)!r} "
                f"size_mb={round(float(total_mb or 0), 2)} "
                f"used_s={round(used, 2)} avg_speed_mb_s={round(avg_speed, 3)}"
            )
            return True, False  # success

        except urllib.error.HTTPError as e:
            end_mono = time.monotonic()
            is_expired = e.code in _EXPIRED_HTTP_CODES

            if is_expired:
                PythonLogger.warning(
                    f"[Download] HTTP {e.code} 链接可能过期: {current_url[:80]}...")
            
            with self.lock:
                if original_url in self.status_map:
                    self.status_map[original_url]["status"] = "error"
                    self.status_map[original_url]["error"] = (
                        f"HTTP {e.code} 链接过期" if is_expired else str(e)
                    )
                    self.status_map[original_url]["usedTime"] = int(end_mono - start_mono)
                    self.status_map[original_url]["completed_at"] = time.time()

            return False, is_expired

        except Exception as e:
            end_mono = time.monotonic()

            # urllib.request.urlretrieve 可能抛 URLError 包裹 HTTPError
            is_expired = False
            err_str = str(e)
            if hasattr(e, 'reason') and hasattr(e.reason, 'status'):
                if e.reason.status in _EXPIRED_HTTP_CODES:
                    is_expired = True
            # 也检查错误消息中的常见过期关键词
            if not is_expired:
                lower_err = err_str.lower()
                if any(kw in lower_err for kw in ['403', '401', '410', 'forbidden', 'unauthorized', 'expired']):
                    is_expired = True

            with self.lock:
                if original_url in self.status_map:
                    self.status_map[original_url]["status"] = "error"
                    self.status_map[original_url]["error"] = (
                        f"链接过期: {err_str}" if is_expired else err_str
                    )
                    self.status_map[original_url]["usedTime"] = int(end_mono - start_mono)
                    self.status_map[original_url]["completed_at"] = time.time()

            return False, is_expired

    def _maybe_range_download(self, current_url: str, original_url: str,
                              save_name: str, manual_size_mb: float,
                              start_mono: float) -> tuple[str, bool, str]:
        """
        尝试实验性 Range 分片下载。

        返回:
        - ("completed", False, "...") 已完成
        - ("fallback", False, "...") 不适合分片,调用方继续单连接下载
        - ("failed", is_expired, "...") 分片下载失败
        """
        file_name = os.path.basename(save_name)
        if not self.enable_range_download:
            with self.lock:
                if original_url in self.status_map:
                    self.status_map[original_url]["range_reason"] = "disabled"
            return "fallback", False, "disabled"

        known_size_mb = float(manual_size_mb or 0)
        if known_size_mb > 0 and known_size_mb < self.range_min_mb:
            reason = f"below_threshold:{round(known_size_mb, 2)}MB<{self.range_min_mb}MB"
            with self.lock:
                if original_url in self.status_map:
                    self.status_map[original_url]["range_reason"] = reason
            return "fallback", False, reason

        PythonLogger.info(
            f"[DownloadRange] probe file={file_name!r} "
            f"manual_size_mb={round(known_size_mb, 2)} "
            f"threshold_mb={self.range_min_mb} max_chunks={self.range_chunks}"
        )

        total_bytes = self._probe_range_total_size(current_url, timeout=10.0)
        if not total_bytes or total_bytes <= 0:
            with self.lock:
                if original_url in self.status_map:
                    self.status_map[original_url]["range_supported"] = False
                    self.status_map[original_url]["range_reason"] = "range_probe_failed"
            return "fallback", False, "range_probe_failed"

        probed_size_mb = total_bytes / (1024 * 1024)
        if probed_size_mb < self.range_min_mb:
            reason = f"below_threshold_after_probe:{round(probed_size_mb, 2)}MB<{self.range_min_mb}MB"
            with self.lock:
                if original_url in self.status_map:
                    self.status_map[original_url]["range_supported"] = True
                    self.status_map[original_url]["range_reason"] = reason
                    self.status_map[original_url]["total_mb"] = round(probed_size_mb, 2)
            return "fallback", False, reason

        min_chunk_bytes = 16 * 1024 * 1024
        chunk_count = min(self.range_chunks, max(1, (total_bytes + min_chunk_bytes - 1) // min_chunk_bytes))
        if chunk_count <= 1:
            with self.lock:
                if original_url in self.status_map:
                    self.status_map[original_url]["range_supported"] = True
                    self.status_map[original_url]["range_reason"] = "only_one_chunk"
            return "fallback", False, "only_one_chunk"

        with self.lock:
            if original_url in self.status_map:
                self.status_map[original_url].update({
                    "mode": "range",
                    "range_supported": True,
                    "range_chunks": int(chunk_count),
                    "range_reason": "enabled",
                    "total_mb": round(total_bytes / (1024 * 1024), 2),
                })

        PythonLogger.info(
            f"[DownloadRange] start file={file_name!r} "
            f"size_mb={round(total_bytes / (1024 * 1024), 2)} chunks={chunk_count}"
        )

        self._cleanup_download_files(save_name)
        part_paths = [f"{save_name}.part{i:03d}" for i in range(chunk_count)]
        part_downloaded = [0 for _ in range(chunk_count)]
        progress_lock = threading.Lock()
        last = {"t": time.monotonic(), "bytes": 0, "speed": 0.0}

        def update_progress(force: bool = False):
            now = time.monotonic()
            with progress_lock:
                downloaded = sum(part_downloaded)
                elapsed = now - last["t"]
                if not force and elapsed < 0.5:
                    return
                newly = downloaded - last["bytes"]
                instant = newly / elapsed if elapsed > 0 else 0.0
                last["speed"] = instant if last["speed"] == 0 else (last["speed"] * 0.3 + instant * 0.7)
                last["t"] = now
                last["bytes"] = downloaded
                speed = last["speed"]

            remaining = max(0, total_bytes - downloaded)
            eta = int(remaining / speed) if speed > 1024 else 0
            with self.lock:
                if original_url in self.status_map:
                    item = self.status_map[original_url]
                    if downloaded > 0 and not item.get("first_progress_at"):
                        item["first_progress_at"] = time.time()
                    item["downloaded_mb"] = round(downloaded / (1024 * 1024), 2)
                    item["total_mb"] = round(total_bytes / (1024 * 1024), 2)
                    item["progress"] = round((downloaded / total_bytes) * 100, 2)
                    item["speed_mb_s"] = round(speed / (1024 * 1024), 2)
                    item["usedTime"] = int(now - start_mono)
                    item["ETA"] = eta

        def download_part(idx: int, start: int, end: int):
            req = urllib.request.Request(
                current_url,
                method="GET",
                headers={"Range": f"bytes={start}-{end}"},
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    status = getattr(resp, "status", resp.getcode())
                    if status != 206:
                        raise RuntimeError(f"range_status_{status}")
                    with open(part_paths[idx], "wb") as f:
                        while True:
                            data = resp.read(256 * 1024)
                            if not data:
                                break
                            f.write(data)
                            with progress_lock:
                                part_downloaded[idx] += len(data)
                            update_progress()
                expected = end - start + 1
                actual = os.path.getsize(part_paths[idx])
                if actual != expected:
                    raise RuntimeError(f"part_size_mismatch:{actual}!={expected}")
            except urllib.error.HTTPError as e:
                raise RuntimeError(f"http_{e.code}") from e

        ranges = []
        chunk_size = total_bytes // chunk_count
        for i in range(chunk_count):
            start = i * chunk_size
            end = total_bytes - 1 if i == chunk_count - 1 else ((i + 1) * chunk_size - 1)
            ranges.append((i, start, end))

        try:
            with ThreadPoolExecutor(max_workers=chunk_count) as pool:
                futures = [pool.submit(download_part, idx, start, end) for idx, start, end in ranges]
                for fut in as_completed(futures):
                    fut.result()

            merge_path = f"{save_name}.merge"
            with open(merge_path, "wb") as out:
                for part in part_paths:
                    with open(part, "rb") as inp:
                        while True:
                            data = inp.read(1024 * 1024)
                            if not data:
                                break
                            out.write(data)
                    try:
                        os.remove(part)
                    except Exception:
                        pass
            os.replace(merge_path, save_name)
            update_progress(force=True)

            end_mono = time.monotonic()
            total_mb = round(total_bytes / (1024 * 1024), 2)
            used = max(0.001, end_mono - start_mono)
            with self.lock:
                if original_url in self.status_map:
                    self.status_map[original_url].update({
                        "status": "completed",
                        "progress": 100.0,
                        "downloaded_mb": total_mb,
                        "total_mb": total_mb,
                        "speed_mb_s": 0.0,
                        "ETA": 0,
                        "usedTime": int(used),
                        "completed_at": time.time(),
                    })
            PythonLogger.info(
                f"[DownloadRange] completed file={file_name!r} "
                f"size_mb={total_mb} chunks={chunk_count} "
                f"used_s={round(used, 2)} avg_speed_mb_s={round(total_mb / used, 3)}"
            )
            return "completed", False, "completed"
        except Exception as e:
            err = str(e)
            lower = err.lower()
            is_expired = any(code in lower for code in ("http_401", "http_403", "http_410"))
            self._cleanup_download_files(save_name)
            with self.lock:
                if original_url in self.status_map:
                    self.status_map[original_url].update({
                        "status": "error",
                        "error": f"分片下载失败: {err}",
                        "usedTime": int(time.monotonic() - start_mono),
                        "completed_at": time.time(),
                    })
            PythonLogger.warning(
                f"[DownloadRange] failed file={file_name!r} "
                f"expired={is_expired} err={err}"
            )
            return "failed", is_expired, err

    def _cleanup_download_files(self, save_name: str):
        try:
            if os.path.exists(save_name):
                os.remove(save_name)
        except Exception:
            pass
        try:
            merge_path = f"{save_name}.merge"
            if os.path.exists(merge_path):
                os.remove(merge_path)
        except Exception:
            pass
        parent = os.path.dirname(save_name) or "."
        base = os.path.basename(save_name)
        try:
            for name in os.listdir(parent):
                if name.startswith(base + ".part"):
                    try:
                        os.remove(os.path.join(parent, name))
                    except Exception:
                        pass
        except Exception:
            pass

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
        "status": "completed",  # waiting/downloading/refreshing/completed/error
        "save_name": "path/to/file.ext",
        "speed_mb_s": 2.5,
        "usedTime": 0,
        "ETA": 0,
        "error": null
    }
]
"""
