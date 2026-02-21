import math
import time
import mimetypes
import threading
import random
import queue
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Any, Dict, Tuple

from dotenv import load_dotenv
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from logger import PythonLogger


# =========================
# Rate Limiter: Token Bucket
# =========================
class TokenBucketRateLimiter:
    """
    rate: 每秒生成多少 token（例如 3 rps）
    burst: 桶容量（允许短时突发）
    """
    def __init__(self, rate: float, burst: int):
        self.rate = float(rate)
        self.capacity = float(burst)
        self.tokens = float(burst)
        self.updated_at = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                elapsed = now - self.updated_at
                if elapsed > 0:
                    self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                    self.updated_at = now

                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return

                missing = tokens - self.tokens
                wait_s = missing / self.rate if self.rate > 1e-9 else 0.5

            time.sleep(min(wait_s, 1.0))


@dataclass
class UploadTask:
    file_path: str
    page_id: str


class Upload:
    def __init__(
        self,
        notion_token: str,
        max_workers: int = 3,
        version: str = "2025-09-03",
        url: str = "https://api.notion.com/v1",
        *,
        queue_maxsize: int = 200,

        max_part_retries: int = 3,
        max_task_restarts: int = 3,

        backoff_base_s: float = 1.0,
        backoff_cap_s: float = 30.0,

        # ✅ 全局 RPS 限制
        rps: float = 3.0,
        burst: int = 6,

        # ✅ 大文件分片大小（建议 15/20/30 MiB）
        part_size_bytes: int = 20 * 1024 * 1024,

        debug: bool = True,
    ):
        self.notion_token = notion_token
        self.max_workers = max_workers
        self.version = version
        self.url = url.rstrip("/")

        self.queue_maxsize = queue_maxsize
        self.max_part_retries = max_part_retries
        self.max_task_restarts = max_task_restarts

        self.backoff_base_s = backoff_base_s
        self.backoff_cap_s = backoff_cap_s

        self.part_size_bytes = part_size_bytes
        self.debug = debug

        self.lock = threading.Lock()
        self.status_map: Dict[str, dict] = {}

        self.default_headers = {
            "Notion-Version": self.version,
            "Authorization": f"Bearer {self.notion_token}",
            "Content-Type": "application/json",
        }

        # ✅ Session 复用连接 + 连接池
        self.session = self._make_session(pool_maxsize=max(16, self.max_workers * 4))

        # ✅ 全局 rate limiter
        self.limiter = TokenBucketRateLimiter(rate=rps, burst=burst)

        # 队列 + worker
        self.task_queue: queue.Queue[UploadTask] = queue.Queue(maxsize=self.queue_maxsize)
        self.stop_event = threading.Event()
        self.workers: list[threading.Thread] = []
        for i in range(self.max_workers):
            t = threading.Thread(target=self._worker_loop, args=(i,), daemon=True)
            t.start()
            self.workers.append(t)

        # 工作区限制
        k = self.get_max_upload_bytes()
        self.max_upload_mib = (k / (1024 * 1024)) if k else None
        self._dbg(
            "__init__",
            f"max_upload_mib={self.max_upload_mib}, workers={self.max_workers}, "
            f"rps={rps}, burst={burst}, part_size={self.part_size_bytes/(1024*1024):.1f}MiB",
        )

    # -------------------------
    # Session
    # -------------------------
    def _make_session(self, pool_maxsize: int) -> requests.Session:
        s = requests.Session()
        retry = Retry(total=0, raise_on_status=False)
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=pool_maxsize,
            pool_maxsize=pool_maxsize,
        )
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        return s

    # -------------------------
    # Debug / Backoff
    # -------------------------
    def _dbg(self, method: str, msg: str) -> None:
        if self.debug:
            PythonLogger.debug(f"[{self.__class__.__name__}-{method}] {msg}")

    def _sleep_backoff(self, *, attempt: int) -> float:
        wait = self.backoff_base_s * (2 ** attempt)
        wait += random.uniform(0, 0.2 * self.backoff_base_s)
        wait = min(wait, self.backoff_cap_s)
        time.sleep(wait)
        return wait

    def _is_retryable_status(self, status_code: int) -> bool:
        return status_code in {429, 500, 502, 503, 504}

    def _retry_after_seconds(self, resp: requests.Response) -> Optional[float]:
        ra = resp.headers.get("Retry-After")
        if not ra:
            return None
        try:
            return float(ra)
        except Exception:
            return None

    # -------------------------
    # Unified Request (Session + RateLimiter + Retry-After)
    # -------------------------
    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        json: Optional[dict] = None,
        data: Any = None,
        files: Any = None,
        timeout: int = 30,
        task_key: Optional[str] = None,
        retry_limit: int = 3,
        apply_rate_limit: bool = True,
    ) -> requests.Response:
        last_exc: Optional[Exception] = None

        for attempt in range(retry_limit + 1):
            if apply_rate_limit:
                self.limiter.acquire(1.0)

            try:
                resp = self.session.request(
                    method,
                    url,
                    headers=headers,
                    json=json,
                    data=data,
                    files=files,
                    timeout=timeout,
                )
                _ = resp.content  # 读完响应体，连接可回收

                if resp.status_code < 400:
                    return resp

                if self._is_retryable_status(resp.status_code):
                    ra = self._retry_after_seconds(resp)
                    if ra is not None:
                        if task_key:
                            self._update_task(task_key, stage="backoff_wait")
                        time.sleep(min(max(ra, 0.0), self.backoff_cap_s))
                        if task_key:
                            self._update_task(task_key, stage="uploading")
                        continue

                    if attempt < retry_limit:
                        if task_key:
                            self._update_task(task_key, stage="backoff_wait")
                        self._sleep_backoff(attempt=attempt)
                        if task_key:
                            self._update_task(task_key, stage="uploading")
                        continue

                resp.raise_for_status()
                return resp

            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
                last_exc = e
                if attempt < retry_limit:
                    if task_key:
                        self._update_task(task_key, stage="backoff_wait")
                    self._sleep_backoff(attempt=attempt)
                    if task_key:
                        self._update_task(task_key, stage="uploading")
                    continue
                raise

        if last_exc:
            raise last_exc
        raise RuntimeError("request failed (unknown)")

    # -------------------------
    # Public: enqueue task
    # -------------------------
    def upload_file(self, file_path: str, page_id: str) -> dict:
        p = Path(file_path)
        if not p.is_file():
            return {"msg": "文件不存在", "file_path": file_path}

        size_bytes = p.stat().st_size
        real_filename = p.name  # ✅ 真实文件名（用于挂载显示/下载）

        with self.lock:
            exist = self.status_map.get(file_path)
            if exist and exist.get("status") in {"waiting", "uploading", "completed"}:
                return {"msg": "任务已存在", "status": exist["status"], "file_path": file_path}

            now_mono = time.monotonic()
            self.status_map[file_path] = {
                "file_path": file_path,
                "page_id": page_id,
                "real_filename": real_filename,  # ✅ 存一份
                "status": "waiting",
                "stage": "waiting",
                "error": None,

                "total_bytes": size_bytes,
                "uploaded_bytes": 0,
                "progress": 0.0,

                "start_mono": now_mono,
                "last_mono": now_mono,
                "last_uploaded_bytes": 0,
                "speed_mib_s": 0.0,
                "eta_s": None,

                "task_restart_attempt": 0,
                "part_retry_attempt": 0,
                "current_part": None,
                "part_total": None,
                "part_done": 0,
                "end_mono": None,
            }

        try:
            self.task_queue.put(UploadTask(file_path=file_path, page_id=page_id), timeout=2.0)
        except queue.Full:
            self._set_error(file_path, "队列已满，任务被拒绝")
            return {"msg": "队列已满，任务被拒绝", "file_path": file_path}

        self._dbg("upload_file", f"任务已入队 file={file_path} size={size_bytes}")
        return {"msg": "任务已入队", "file_path": file_path, "page_id": page_id}

    def list_status(self) -> list[dict]:
        with self.lock:
            snapshot = [dict(v) for v in self.status_map.values()]

        out = []
        now_mono = time.monotonic()

        for t in snapshot:
            total_bytes = t.get("total_bytes") or 0
            uploaded_bytes = t.get("uploaded_bytes") or 0

            total_mib = total_bytes / (1024 * 1024) if total_bytes else 0.0
            uploaded_mib = uploaded_bytes / (1024 * 1024) if uploaded_bytes else 0.0

            start = t.get("start_mono") or now_mono
            end = t.get("end_mono") or now_mono
            used = max(0.0, end - start)
            speed = t.get("speed_mib_s", 0.0)
            eta = t.get("eta_s", None)

            progress = (uploaded_bytes / total_bytes * 100.0) if total_bytes else 0.0
            progress = min(100.0, progress)

            out.append({
                "progress": round(progress, 2),
                "uploaded_mb": round(uploaded_mib, 3),
                "total_mb": round(total_mib, 3),
                "status": t.get("status"),
                "stage": t.get("stage"),
                "file_path": t.get("file_path"),
                "page_id": t.get("page_id"),
                "real_filename": t.get("real_filename"),
                "usedTime": int(used),
                "ETA": 0 if progress >= 100.0 else eta,
                "speed_mb_s": round(speed, 3),
                "error": t.get("error"),
                "task_restart_attempt": t.get("task_restart_attempt"),
                "part_retry_attempt": t.get("part_retry_attempt"),
                "current_part": t.get("current_part"),
                "part_done": t.get("part_done"),
                "part_total": t.get("part_total"),
            })
        return out

    def shutdown(self, wait: bool = True) -> None:
        self.stop_event.set()
        if wait:
            try:
                self.task_queue.join()
            except Exception:
                pass
            for t in self.workers:
                t.join(timeout=1.0)
        try:
            self.session.close()
        except Exception:
            pass

    # -------------------------
    # Worker Loop
    # -------------------------
    def _worker_loop(self, worker_id: int) -> None:
        self._dbg(f"_worker_loop#{worker_id}", "worker started")
        while not self.stop_event.is_set():
            try:
                task = self.task_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                self._run_task_with_restarts(task.file_path, task.page_id, worker_id)
            finally:
                self.task_queue.task_done()
        self._dbg(f"_worker_loop#{worker_id}", "worker stopped")

    def _run_task_with_restarts(self, file_path: str, page_id: str, worker_id: int) -> None:
        for restart_attempt in range(self.max_task_restarts + 1):
            self._update_task(
                file_path,
                status="uploading",
                stage="creating",
                error=None,
                task_restart_attempt=restart_attempt,
                part_retry_attempt=0,
                current_part=None,
                part_done=0,
            )
            try:
                self._run_once(file_path, page_id)
                return
            except Exception as e:
                self._dbg(f"_task#{worker_id}", f"failed restart={restart_attempt} err={e!r}")
                if restart_attempt >= self.max_task_restarts:
                    self._set_error(file_path, f"任务重启次数耗尽：{e!r}")
                    return
                self._update_task(file_path, stage="backoff_wait")
                self._sleep_backoff(attempt=restart_attempt)

    # -------------------------
    # One Run
    # -------------------------
    def _run_once(self, file_path: str, page_id: str) -> None:
        p = Path(file_path)
        if not p.is_file():
            raise RuntimeError("File not found")

        size_bytes = p.stat().st_size
        size_mib = size_bytes / (1024 * 1024)
        real_filename = p.name  # ✅ 真实文件名（用于挂载）

        if self.max_upload_mib is not None and size_mib > self.max_upload_mib:
            raise RuntimeError(f"文件大小 {size_mib:.2f}MiB 超过上限 {self.max_upload_mib:.2f}MiB")

        # upload_filename 可能是“伪装名”（.txt），content_type 也可能是 text/plain
        content_type, upload_filename = self.get_mime_type(file_path)

        TWENTY_MIB_BYTES = 20 * 1024 * 1024
        self._update_task(file_path, stage="creating")

        if size_bytes > TWENTY_MIB_BYTES:
            part_size = self.part_size_bytes
            part_total = math.ceil(size_bytes / part_size)
            self._update_task(file_path, part_total=part_total, part_done=0)

            fu = self._create_file_upload(
                mode="multi_part",
                filename=upload_filename,
                content_type=content_type,
                number_of_parts=part_total,
                task_key=file_path,
            )
            file_upload_id = fu["id"]
            upload_url = fu["upload_url"]

            self._update_task(file_path, stage="uploading")
            self._upload_parts_serial_with_retry(
                file_path=file_path,
                upload_url=upload_url,
                upload_filename=upload_filename,
                content_type=content_type,
                part_size=part_size,
                part_total=part_total,
            )

            self._update_task(file_path, stage="completing")
            self._complete_file_upload(file_upload_id, task_key=file_path)

        else:
            fu = self._create_file_upload(
                mode="single_part",
                filename=upload_filename,
                content_type=content_type,
                task_key=file_path,
            )
            file_upload_id = fu["id"]
            upload_url = fu["upload_url"]

            self._update_task(file_path, stage="uploading")
            self._send_single_file(
                task_key=file_path,
                upload_url=upload_url,
                local_path=file_path,
                upload_filename=upload_filename,
                content_type=content_type,
            )

        # ✅ 挂载：把 name 设置成真实文件名（关键）
        self._update_task(file_path, stage="attaching")
        self._attach_to_page_as_file_block(
            page_id,
            file_upload_id,
            task_key=file_path,
            display_name=real_filename,
        )
        self._update_task(
            file_path,
            status="completed",
            stage="done",
            uploaded_bytes=size_bytes,
            progress=100.0,
            end_mono=time.monotonic(),
        )

    # -------------------------
    # Serial parts + per-part retry (HIGH THROUGHPUT)
    # -------------------------
    def _upload_parts_serial_with_retry(
        self,
        *,
        file_path: str,
        upload_url: str,
        upload_filename: str,
        content_type: str,
        part_size: int,
        part_total: int,
    ) -> None:
        uploaded_acc = 0
        with open(file_path, "rb") as f:
            for part_no in range(1, part_total + 1):
                chunk = f.read(part_size)
                if not chunk:
                    break

                self._update_task(file_path, current_part=part_no)

                self._send_part_with_retry(
                    task_key=file_path,
                    upload_url=upload_url,
                    upload_filename=upload_filename,
                    content_type=content_type,
                    part_number=part_no,
                    payload_bytes=chunk,
                )

                uploaded_acc += len(chunk)
                self._update_progress(file_path, uploaded_acc)
                self._update_task(file_path, part_done=part_no)

    def _send_part_with_retry(
        self,
        *,
        task_key: str,
        upload_url: str,
        upload_filename: str,
        content_type: str,
        part_number: Optional[int],
        payload_bytes: bytes,
    ) -> None:
        last_exc: Optional[Exception] = None

        for attempt in range(self.max_part_retries + 1):
            self._update_task(task_key, part_retry_attempt=attempt)
            try:
                self._send_upload_fast(
                    task_key=task_key,
                    upload_url=upload_url,
                    upload_filename=upload_filename,
                    content_type=content_type,
                    part_number=part_number,
                    payload_bytes=payload_bytes,
                )
                return
            except Exception as e:
                last_exc = e
                if attempt >= self.max_part_retries:
                    break
                self._update_task(task_key, stage="backoff_wait")
                self._sleep_backoff(attempt=attempt)
                self._update_task(task_key, stage="uploading")

        raise RuntimeError(f"send part failed: {last_exc!r}")

    def _send_upload_fast(
        self,
        *,
        task_key: str,
        upload_url: str,
        upload_filename: str,
        content_type: str,
        part_number: Optional[int],
        payload_bytes: bytes,
    ) -> None:
        data = {"part_number": str(part_number)} if part_number is not None else None
        files = {"file": (upload_filename, payload_bytes, content_type)}
        resp = self._request(
            "POST",
            upload_url,
            headers={
                "Authorization": self.default_headers["Authorization"],
                "Notion-Version": self.default_headers["Notion-Version"],
            },
            data=data,
            files=files,
            timeout=600,
            task_key=task_key,
            retry_limit=3,
            apply_rate_limit=False,
        )
        # ✅ upload_url 有时不返回 JSON，尽力解析但不强依赖
        try:
            _ = resp.json()
        except (ValueError, Exception):
            pass

    def _send_single_file(
        self,
        *,
        task_key: str,
        upload_url: str,
        local_path: str,
        upload_filename: str,
        content_type: str,
    ) -> None:
        payload = Path(local_path).read_bytes()  # <=20MiB
        self._send_part_with_retry(
            task_key=task_key,
            upload_url=upload_url,
            upload_filename=upload_filename,
            content_type=content_type,
            part_number=None,
            payload_bytes=payload,
        )
        self._update_progress(task_key, len(payload))

    # -------------------------
    # Progress update (COARSE: per-part only)
    # -------------------------
    def _update_progress(self, task_key: str, uploaded_total: int) -> None:
        now = time.monotonic()
        with self.lock:
            t = self.status_map.get(task_key, {})
            total_bytes = t.get("total_bytes") or 0

            t["uploaded_bytes"] = uploaded_total
            if total_bytes > 0:
                t["progress"] = min(100.0, uploaded_total / total_bytes * 100.0)

            last_t = t.get("last_mono", now)
            last_u = t.get("last_uploaded_bytes", uploaded_total)
            dt = now - last_t
            du = uploaded_total - last_u

            if dt >= 0.5:
                speed_mib_s = (du / (1024 * 1024)) / dt if dt > 0 else 0.0
                t["speed_mib_s"] = speed_mib_s
                remain_bytes = max(0, total_bytes - uploaded_total)
                t["eta_s"] = int((remain_bytes / (1024 * 1024)) / speed_mib_s) if speed_mib_s > 1e-9 else None
                t["last_mono"] = now
                t["last_uploaded_bytes"] = uploaded_total

            self.status_map[task_key] = t

    # -------------------------
    # Notion APIs
    # -------------------------
    def get_max_upload_bytes(self) -> Optional[int]:
        resp = self._request(
            "GET",
            f"{self.url}/users/me",
            headers=self.default_headers,
            timeout=30,
            task_key=None,
            retry_limit=3,
        )
        data = resp.json()
        limits = data.get("workspace_limits") or {}
        return limits.get("max_file_upload_size_in_bytes")

    def _create_file_upload(
        self,
        *,
        mode: str,
        filename: str,
        content_type: str,
        number_of_parts: Optional[int] = None,
        task_key: Optional[str],
    ) -> dict:
        payload = {"mode": mode, "filename": filename, "content_type": content_type}
        if number_of_parts is not None:
            payload["number_of_parts"] = number_of_parts

        resp = self._request(
            "POST",
            f"{self.url}/file_uploads",
            headers=self.default_headers,
            json=payload,
            timeout=30,
            task_key=task_key,
            retry_limit=3,
        )
        return resp.json()

    def _complete_file_upload(self, file_upload_id: str, *, task_key: Optional[str]) -> dict:
        resp = self._request(
            "POST",
            f"{self.url}/file_uploads/{file_upload_id}/complete",
            headers=self.default_headers,
            json={},
            timeout=30,
            task_key=task_key,
            retry_limit=3,
        )
        return resp.json()

    def _attach_to_page_as_file_block(
        self,
        page_id: str,
        file_upload_id: str,
        *,
        task_key: Optional[str],
        display_name: str,
    ) -> dict:
        """
        将上传完成的文件挂载到页面。
        v1.4.2: 根据文件扩展名自动选择原生块类型 (image/video/audio/pdf/file)。
        """
        block_type = self._detect_notion_block_type(display_name)
        caption = [{"type": "text", "text": {"content": display_name}}]

        if block_type == "file":
            # file 块支持 name 字段
            block_content = {
                "type": "file_upload",
                "file_upload": {"id": file_upload_id},
                "caption": caption,
                "name": display_name,
            }
        else:
            # image/video/audio/pdf 块不支持 name 字段，仅支持 caption
            block_content = {
                "type": "file_upload",
                "file_upload": {"id": file_upload_id},
                "caption": caption,
            }

        payload = {
            "children": [
                {
                    "type": block_type,
                    block_type: block_content,
                }
            ]
        }

        self._dbg("_attach_to_page", f"block_type={block_type}, display_name={display_name}")

        resp = self._request(
            "PATCH",
            f"{self.url}/blocks/{page_id}/children",
            headers=self.default_headers,
            json=payload,
            timeout=30,
            task_key=task_key,
            retry_limit=3,
        )
        return resp.json()

    # -------------------------
    # Native Block Type Detection (v1.4.2-Status)
    # -------------------------
    # 文件扩展名 → Notion 原生块类型映射
    _IMAGE_EXTS = frozenset({
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
        ".bmp", ".ico", ".tiff", ".tif", ".heic", ".heif",
    })
    _VIDEO_EXTS = frozenset({
        ".mp4", ".webm", ".mov", ".avi", ".mkv", ".flv",
        ".wmv", ".m4v", ".f4v", ".asf", ".amv", ".mpeg", ".mpg",
    })
    _AUDIO_EXTS = frozenset({
        ".mp3", ".wav", ".ogg", ".aac", ".flac", ".m4a",
        ".wma", ".midi", ".mid", ".opus",
    })
    _PDF_EXTS = frozenset({".pdf"})

    @classmethod
    def _detect_notion_block_type(cls, filename: str) -> str:
        """
        根据文件扩展名检测应使用的 Notion 原生块类型。(v1.4.2-Status)

        映射规则:
          - 图片 (.jpg/.png/.gif/...) → "image"
          - 视频 (.mp4/.webm/.mov/...) → "video"
          - 音频 (.mp3/.wav/.ogg/...) → "audio"
          - PDF (.pdf)                → "pdf"
          - 其他所有文件              → "file"

        返回: Notion block type 字符串
        """
        ext = Path(filename).suffix.lower()

        # 去除伪装后缀 .txt（上传时 MIME 不支持的文件会被加上 .txt）
        if ext == ".txt":
            base_name = Path(filename).stem
            real_ext = Path(base_name).suffix.lower()
            if real_ext:
                ext = real_ext

        if ext in cls._IMAGE_EXTS:
            return "image"
        elif ext in cls._VIDEO_EXTS:
            return "video"
        elif ext in cls._AUDIO_EXTS:
            return "audio"
        elif ext in cls._PDF_EXTS:
            return "pdf"
        else:
            return "file"

    # -------------------------
    # MIME
    # -------------------------
    def get_mime_type(self, file_path: str) -> Tuple[str, str]:
        NOTION_SUPPORTED_MIME = {
            "audio/aac", "audio/midi", "audio/mpeg", "audio/mp4", "audio/ogg", "audio/wav", "audio/x-ms-wma",
            "application/pdf", "text/plain", "application/json",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.template",
            "application/vnd.ms-powerpoint",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.presentationml.template",
            "image/gif", "image/heic", "image/jpeg", "image/png", "image/svg+xml", "image/tiff", "image/webp",
            "image/vnd.microsoft.icon",
            "video/x-amv", "video/x-ms-asf", "video/x-msvideo", "video/x-f4v", "video/x-flv",
            "video/mp4", "application/mp4", "video/webm", "video/quicktime", "video/mpeg",
        }

        p = Path(file_path)
        name = p.name
        mime, _ = mimetypes.guess_type(str(p))

        # 支持则原样
        if mime in NOTION_SUPPORTED_MIME:
            return mime, name

        # 不支持：伪装成 text/plain + .txt（上传侧）
        if not name.lower().endswith(".txt"):
            name = name + ".txt"
        return "text/plain", name

    # -------------------------
    # Status helpers
    # -------------------------
    def _update_task(self, task_key: str, **kwargs) -> None:
        with self.lock:
            t = self.status_map.get(task_key)
            if not t:
                return
            t.update(kwargs)
            self.status_map[task_key] = t

    def _set_error(self, task_key: str, msg: str) -> None:
        with self.lock:
            t = self.status_map.get(task_key)
            if not t:
                return
            t.update({"status": "error", "stage": "failed", "error": msg, "end_mono": time.monotonic()})
            self.status_map[task_key] = t
        self._dbg("_set_error", f"task={task_key} error={msg}")


if __name__ == "__main__":
    load_dotenv()
    token = os.getenv("NOTION_TOKEN", "")
    if not token:
        raise RuntimeError("Please set NOTION_TOKEN env var")

    u = Upload(
        notion_token=token,
        max_workers=1,        # 单文件测速建议 1
        rps=3.0,
        burst=4,
        part_size_bytes=15 * 1024 * 1024,
        debug=True,
    )

    u.upload_file(
        "C:/Ruibin_Ningh/program/Notion-Files-Management-Beta/Notion-Files-Management.7z",
        "2fc644ea-d11a-8010-9665-e5fbaba0fd58",
    )

    try:
        while True:
            time.sleep(1)
            print(u.list_status())
    except KeyboardInterrupt:
        u.shutdown(True)
        print("shutdown")
