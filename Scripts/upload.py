import math
import os
import time
import mimetypes
import threading
import random
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder, MultipartEncoderMonitor


class Upload:
    def __init__(
        self,
        notion_token: str,
        max_workers: int = 3,
        version: str = "2025-09-03",
        url: str = "https://api.notion.com/v1",
        *,
        # ✅ 新增：分片重试次数 & 任务重启次数（默认都是 3）
        max_part_retries: int = 3,
        max_task_restarts: int = 3,
        # ✅ 新增：指数退避参数（可不改，默认够用）
        backoff_base_s: float = 1.0,
        backoff_cap_s: float = 30.0,
        # ✅ 新增：调试开关
        debug: bool = True,
    ):
        self.notion_token = notion_token
        self.max_workers = max_workers
        self.version = version
        self.url = url

        self.max_part_retries = max_part_retries
        self.max_task_restarts = max_task_restarts
        self.backoff_base_s = backoff_base_s
        self.backoff_cap_s = backoff_cap_s
        self.debug = debug

        self.lock = threading.Lock()
        self.status_map: dict[str, dict] = {}

        # JSON 接口默认请求头（Create/Complete/Attach 等）
        self.default_headers = {
            "Notion-Version": self.version,
            "Authorization": f"Bearer {self.notion_token}",
            "Content-Type": "application/json",
        }

        # 线程池：限制并发，避免无限开线程
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)

        # 获取工作区单文件最大上传限制（bytes -> MiB）
        k = self.get_max_upload_bytes()
        self.max_upload_mib = (k / (1024 * 1024)) if k else None
        self._dbg("__init__", f"max_upload_mib={self.max_upload_mib}")

    # -------------------------
    # Debug：统一输出格式
    # -------------------------
    def _dbg(self, method: str, msg: str) -> None:
        if self.debug:
            print(f"[{self.__class__.__name__}-{method}] {msg}")

    # -------------------------
    # Backoff：指数退避等待
    # -------------------------
    def _sleep_backoff(self, *, attempt: int) -> float:
        """
        指数退避：base * 2^attempt + jitter（抖动），并做上限封顶。
        attempt 从 0 开始：第一次失败后等待 attempt=0。
        """
        wait = self.backoff_base_s * (2 ** attempt)
        # 加一点抖动，避免多线程同时重试造成“同步风暴”
        wait += random.uniform(0, 0.2 * self.backoff_base_s)
        wait = min(wait, self.backoff_cap_s)
        time.sleep(wait)
        return wait

    def _is_retryable(self, exc: Exception) -> bool:
        """
        判断该错误是否值得重试：
        - 网络错误/超时/连接中断
        - HTTP 429/500/502/503/504 这类临时性错误
        """
        if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
            return True
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            return exc.response.status_code in {429, 500, 502, 503, 504}
        return False

    # -------------------------
    # 公开方法：提交任务 + 查询任务
    # -------------------------
    def upload_file(self, file_path: str, page_id: str) -> dict:
        """
        提交上传任务到线程池。
        """
        method = "upload_file"
        p = Path(file_path)
        if not p.is_file():
            return {"msg": "文件不存在", "file_path": file_path}

        size_bytes = p.stat().st_size

        with self.lock:
            # 去重：同路径且状态未结束则不重复提交
            exist = self.status_map.get(file_path)
            if exist and exist.get("status") in {"waiting", "uploading", "completed"}:
                return {"msg": "任务已存在", "status": exist["status"], "file_path": file_path}

            # ✅ 初始化任务状态（更丰富）
            now_mono = time.monotonic()
            self.status_map[file_path] = {
                "file_path": file_path,
                "page_id": page_id,

                # status：大状态；stage：细阶段
                "status": "waiting",     # waiting/uploading/completed/error
                "stage": "waiting",      # waiting/creating/uploading/attaching/done/failed/backoff_wait
                "error": None,

                "total_bytes": size_bytes,
                "uploaded_bytes": 0,
                "progress": 0.0,

                # ✅ 用单调时钟统计耗时/速度，避免系统时间变化影响
                "start_mono": now_mono,
                "last_mono": now_mono,
                "last_uploaded_bytes": 0,
                "speed_mib_s": 0.0,
                "eta_s": None,

                # ✅ 重试相关计数
                "task_restart_attempt": 0,
                "part_retry_attempt": 0,
                "current_part": None,
                "part_total": None,
                "part_done": 0,
            }

            fut = self.executor.submit(self._worker, file_path, page_id)
            self.status_map[file_path]["future"] = fut

        self._dbg(method, f"任务已提交 file={file_path} page={page_id} size={size_bytes} bytes")
        return {"msg": "任务已提交", "file_path": file_path, "page_id": page_id}

    def list_status(self) -> list[dict]:
        """
        查询所有任务状态，返回你指定的列表结构。
        """
        with self.lock:
            snapshot = [dict(v) for v in self.status_map.values()]

        out = []
        now_mono = time.monotonic()

        for t in snapshot:
            total_bytes = t.get("total_bytes") or 0
            uploaded_bytes = t.get("uploaded_bytes") or 0

            total_mib = total_bytes / (1024 * 1024) if total_bytes else 0.0
            uploaded_mib = uploaded_bytes / (1024 * 1024) if uploaded_bytes else 0.0

            used = max(0.0, now_mono - (t.get("start_mono") or now_mono))

            # ✅ 速度/ETA：优先使用回调计算的“滑动窗口速度”
            speed = t.get("speed_mib_s", 0.0)
            eta = t.get("eta_s", None)

            progress = 0.0
            if total_bytes > 0:
                progress = min(100.0, uploaded_bytes / total_bytes * 100.0)

            out.append({
                "progress": round(progress, 2),
                "uploaded_mb": round(uploaded_mib, 3),
                "total_mb": round(total_mib, 3),
                "status": t.get("status"),
                "stage": t.get("stage"),  # ✅ 新增：更细阶段
                "file_path": t.get("file_path"),
                "page_id": t.get("page_id"),
                "usedTime": int(used),
                "ETA": 0 if progress >= 100.0 else eta,
                "speed_mb_s": round(speed, 3),
                "error": t.get("error"),

                # ✅ 新增：调试/排查非常有用
                "task_restart_attempt": t.get("task_restart_attempt"),
                "part_retry_attempt": t.get("part_retry_attempt"),
                "current_part": t.get("current_part"),
                "part_done": t.get("part_done"),
                "part_total": t.get("part_total"),
            })

        return out

    # -------------------------
    # 工作区上限：/users/me
    # -------------------------
    def get_max_upload_bytes(self) -> int | None:
        """
        获取当前 token 对应 bot 的单文件最大上传大小（字节数）。
        """
        r = requests.get(
            f"{self.url}/users/me",
            headers=self.default_headers,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        limits = data.get("workspace_limits") or {}
        return limits.get("max_file_upload_size_in_bytes")

    # -------------------------
    # MIME/文件名推断
    # -------------------------
    def get_mime_type(self, file_path: str) -> tuple[str, str]:
        """
        输入文件路径，返回 (content_type, upload_filename)。
        不支持的 MIME 统一伪装为 text/plain + .txt
        """
        NOTION_SUPPORTED_MIME = {
            # Audio
            "audio/aac", "audio/midi", "audio/mpeg", "audio/mp4", "audio/ogg", "audio/wav", "audio/x-ms-wma",
            # Document
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
            # Image
            "image/gif", "image/heic", "image/jpeg", "image/png", "image/svg+xml", "image/tiff", "image/webp",
            "image/vnd.microsoft.icon",
            # Video
            "video/x-amv", "video/x-ms-asf", "video/x-msvideo", "video/x-f4v", "video/x-flv",
            "video/mp4", "application/mp4", "video/webm", "video/quicktime", "video/mpeg",
        }

        p = Path(file_path)
        name = p.name
        mime, _ = mimetypes.guess_type(str(p))

        if mime in NOTION_SUPPORTED_MIME:
            return mime, name

        if not name.lower().endswith(".txt"):
            name = name + ".txt"
        return "text/plain", name

    # -------------------------
    # Worker：加入“任务重启”外层循环
    # -------------------------
    def _worker(self, file_path: str, page_id: str) -> None:
        """
        外层：任务级重启（从头 Create + 从头上传）
        内层：单次执行（_run_once）
        """
        method = "_worker"
        self._dbg(method, f"开始执行任务 file={file_path}")

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
            self._dbg(method, f"任务轮次 restart={restart_attempt}/{self.max_task_restarts}")

            try:
                self._run_once(file_path, page_id)
                self._dbg(method, "任务完成 ✅")
                return
            except Exception as e:
                # 如果已经到达重启上限，直接失败
                self._dbg(method, f"本轮失败 err={e!r}")
                if restart_attempt >= self.max_task_restarts:
                    self._set_error(file_path, f"任务重启次数耗尽：{e!r}")
                    return

                # 进入任务级 backoff 等待后重启
                self._update_task(file_path, stage="backoff_wait")
                waited = self._sleep_backoff(attempt=restart_attempt)
                self._dbg(method, f"准备任务重启，等待 {waited:.2f}s")

    def _run_once(self, file_path: str, page_id: str) -> None:
        """
        单次任务执行（不包含任务重启循环）：
        - small：Create -> Send -> Attach
        - large：Create -> Send(parts) -> Complete -> Attach
        """
        method = "_run_once"

        p = Path(file_path)
        if not p.is_file():
            raise RuntimeError("File not found")

        size_bytes = p.stat().st_size
        size_mib = size_bytes / (1024 * 1024)

        # 工作区上限检查
        if self.max_upload_mib is not None and size_mib > self.max_upload_mib:
            raise RuntimeError(f"文件大小 {size_mib:.2f}MiB 超过上限 {self.max_upload_mib:.2f}MiB")

        content_type, upload_filename = self.get_mime_type(file_path)
        self._dbg(method, f"content_type={content_type}, upload_filename={upload_filename}, size_mib={size_mib:.2f}")

        TWENTY_MIB_BYTES = 20 * 1024 * 1024

        # 申请上传（creating）
        self._update_task(file_path, stage="creating")

        if size_bytes > TWENTY_MIB_BYTES:
            # ---------- multi_part ----------
            part_size = 10 * 1024 * 1024
            part_total = math.ceil(size_bytes / part_size)

            self._update_task(file_path, part_total=part_total, part_done=0)
            self._dbg(method, f"multi_part create part_total={part_total}, part_size={part_size}")

            fu = self._create_file_upload(
                mode="multi_part",
                filename=upload_filename,
                content_type=content_type,
                number_of_parts=part_total,
            )
            file_upload_id = fu["id"]
            upload_url = fu["upload_url"]
            self._dbg(method, f"create ok file_upload_id={file_upload_id}")

            # 上传阶段（uploading）
            self._update_task(file_path, stage="uploading")
            self._upload_parts_with_retry(
                file_path=file_path,
                upload_url=upload_url,
                upload_filename=upload_filename,
                content_type=content_type,
                part_size=part_size,
                part_total=part_total,
            )

            # complete（completing）
            self._update_task(file_path, stage="completing")
            self._dbg(method, "complete multi_part")
            self._complete_file_upload(file_upload_id)

        else:
            # ---------- single_part ----------
            self._dbg(method, "single_part create")
            fu = self._create_file_upload(
                mode="single_part",
                filename=upload_filename,
                content_type=content_type,
            )
            file_upload_id = fu["id"]
            upload_url = fu["upload_url"]
            self._dbg(method, f"create ok file_upload_id={file_upload_id}")

            self._update_task(file_path, stage="uploading")
            self._send_with_retry(
                task_key=file_path,
                upload_url=upload_url,
                local_path=file_path,
                upload_filename=upload_filename,
                content_type=content_type,
                base_uploaded_bytes=0,
                part_len_bytes=size_bytes,
                part_number=None,
            )

        # 挂载（attaching）
        self._update_task(file_path, stage="attaching")
        self._dbg(method, f"attach to page/block {page_id}")
        self._attach_to_page_as_file_block(page_id, file_upload_id)

        # 完成（done）
        self._update_task(file_path, status="completed", stage="done", uploaded_bytes=size_bytes, progress=100.0)

    # -------------------------
    # multi_part：分片上传（带重试）
    # -------------------------
    def _upload_parts_with_retry(
        self,
        *,
        file_path: str,
        upload_url: str,
        upload_filename: str,
        content_type: str,
        part_size: int,
        part_total: int,
    ) -> None:
        """
        对每个分片执行：
        - 写临时文件
        - 调用 _send_with_retry（分片级重试 + 指数退避）
        - 成功后删除临时文件
        - 失败（重试耗尽）直接抛异常，触发任务重启
        """
        method = "_upload_parts_with_retry"
        uploaded_bytes_acc = 0

        with open(file_path, "rb") as f:
            for part_no in range(1, part_total + 1):
                chunk = f.read(part_size)
                if not chunk:
                    break

                tmp_path = f"{file_path}.part{part_no:04d}"
                part_len = len(chunk)

                # 写临时分片文件
                with open(tmp_path, "wb") as pf:
                    pf.write(chunk)

                self._update_task(file_path, current_part=part_no)
                self._dbg(method, f"part {part_no}/{part_total} bytes={part_len} tmp={tmp_path}")

                try:
                    self._send_with_retry(
                        task_key=file_path,
                        upload_url=upload_url,
                        local_path=tmp_path,
                        upload_filename=upload_filename,
                        content_type=content_type,
                        base_uploaded_bytes=uploaded_bytes_acc,
                        part_len_bytes=part_len,
                        part_number=part_no,
                    )
                finally:
                    # 无论成功或失败，都尽量清理临时文件（避免残留）
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

                uploaded_bytes_acc += part_len
                self._update_task(file_path, part_done=part_no)
                self._dbg(method, f"part done {part_no}/{part_total}")

    # -------------------------
    # 分片级重试封装：指数退避
    # -------------------------
    def _send_with_retry(
        self,
        *,
        task_key: str,
        upload_url: str,
        local_path: str,
        upload_filename: str,
        content_type: str,
        base_uploaded_bytes: int,
        part_len_bytes: int,
        part_number: int | None,
    ) -> dict:
        """
        对 _send_upload_with_progress 增加“分片级重试”：
        - retry 次数：max_part_retries
        - 每次失败后指数退避
        - 若超过重试次数仍失败：抛异常 -> 上层触发任务重启
        """
        method = "_send_with_retry"
        last_exc: Exception | None = None

        for attempt in range(self.max_part_retries + 1):
            self._update_task(task_key, part_retry_attempt=attempt)

            label = "single" if part_number is None else f"part={part_number}"
            self._dbg(method, f"{label} try {attempt}/{self.max_part_retries}")

            try:
                return self._send_upload_with_progress(
                    upload_url=upload_url,
                    local_path=local_path,
                    upload_filename=upload_filename,
                    content_type=content_type,
                    task_key=task_key,
                    base_uploaded_bytes=base_uploaded_bytes,
                    part_len_bytes=part_len_bytes,
                    part_number=part_number,
                )

            except Exception as e:
                last_exc = e
                retryable = self._is_retryable(e)
                self._dbg(method, f"{label} failed retryable={retryable} err={e!r}")

                # 不可重试：直接退出（交给任务重启）
                if not retryable:
                    break

                # 已经到最后一次还失败：退出（交给任务重启）
                if attempt >= self.max_part_retries:
                    break

                # backoff 等待后再试
                self._update_task(task_key, stage="backoff_wait")
                waited = self._sleep_backoff(attempt=attempt)
                self._dbg(method, f"{label} backoff wait {waited:.2f}s")
                self._update_task(task_key, stage="uploading")

        # 触发任务重启（上层 _worker 会捕获并重启任务）
        raise RuntimeError(f"分片上传失败且重试耗尽：{last_exc!r}")

    # -------------------------
    # Notion：Create / Send / Complete / Attach
    # -------------------------
    def _create_file_upload(
        self,
        mode: str,
        filename: str,
        content_type: str,
        number_of_parts: int | None = None,
    ) -> dict:
        method = "_create_file_upload"
        payload = {"mode": mode, "filename": filename, "content_type": content_type}
        if number_of_parts is not None:
            payload["number_of_parts"] = number_of_parts

        self._dbg(method, f"POST /file_uploads mode={mode} filename={filename} parts={number_of_parts}")
        r = requests.post(
            f"{self.url}/file_uploads",
            headers=self.default_headers,
            json=payload,
            timeout=30,
        )
        self._dbg(method, f"HTTP {r.status_code}")
        r.raise_for_status()
        return r.json()

    def _send_upload_with_progress(
        self,
        *,
        upload_url: str,
        local_path: str,
        upload_filename: str,
        content_type: str,
        task_key: str,
        base_uploaded_bytes: int,
        part_len_bytes: int,
        part_number: int | None = None,
    ) -> dict:
        """
        Send：multipart/form-data 上传数据 + 进度回调更新速度/ETA。
        """
        method = "_send_upload_with_progress"

        fields = {}
        if part_number is not None:
            fields["part_number"] = str(part_number)

        f = open(local_path, "rb")
        fields["file"] = (upload_filename, f, content_type)

        encoder = MultipartEncoder(fields=fields)

        # 控制“写回状态”的频率（越小越实时，但也更耗；0.2~0.5 推荐）
        STATUS_PUSH_INTERVAL_S = 0.3

        last_push_mono = time.monotonic()

        def cb(m: MultipartEncoderMonitor):
            nonlocal last_push_mono
            now = time.monotonic()

            # 当前请求已发送字节 -> 合并成全局累计
            uploaded_total = base_uploaded_bytes + min(m.bytes_read, part_len_bytes)

            # ✅ 高频回调直接返回：不加锁、不改 dict
            if now - last_push_mono < STATUS_PUSH_INTERVAL_S:
                return
            last_push_mono = now

            # ✅ 只有低频写回才加锁
            with self.lock:
                t = self.status_map.get(task_key, {})
                total_bytes = t.get("total_bytes") or 0

                # 进度（低频写回也足够准）
                t["uploaded_bytes"] = uploaded_total
                if total_bytes > 0:
                    t["progress"] = min(100.0, uploaded_total / total_bytes * 100.0)

                # 滑动窗口速度：dt >= 0.5s 才更新，减少抖动
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

        monitor = MultipartEncoderMonitor(encoder, cb)

        headers = {
            "Authorization": self.default_headers["Authorization"],
            "Notion-Version": self.default_headers["Notion-Version"],
            # ✅ 让 toolbelt 自动提供带 boundary 的 content-type（不要手写）
            "Content-Type": monitor.content_type,
        }

        try:
            self._dbg(method, f"POST upload_url part={part_number} file={local_path}")
            r = requests.post(upload_url, data=monitor, headers=headers, timeout=600)
            self._dbg(method, f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        finally:
            f.close()

    def _complete_file_upload(self, file_upload_id: str) -> dict:
        method = "_complete_file_upload"
        self._dbg(method, f"POST /file_uploads/{file_upload_id}/complete")
        r = requests.post(
            f"{self.url}/file_uploads/{file_upload_id}/complete",
            headers=self.default_headers,
            json={},
            timeout=30,
        )
        self._dbg(method, f"HTTP {r.status_code}")
        r.raise_for_status()
        return r.json()

    def _attach_to_page_as_file_block(self, page_id: str, file_upload_id: str) -> dict:
        method = "_attach_to_page_as_file_block"
        payload = {
            "children": [
                {
                    "type": "file",
                    "file": {
                        "type": "file_upload",
                        "file_upload": {"id": file_upload_id},
                    },
                }
            ]
        }
        self._dbg(method, f"PATCH /blocks/{page_id}/children attach file_upload_id={file_upload_id}")
        r = requests.patch(
            f"{self.url}/blocks/{page_id}/children",
            headers=self.default_headers,
            json=payload,
            timeout=30,
        )
        self._dbg(method, f"HTTP {r.status_code}")
        r.raise_for_status()
        return r.json()

    # -------------------------
    # 任务状态更新（线程安全）
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
            t.update({"status": "error", "stage": "failed", "error": msg})
            self.status_map[task_key] = t
        self._dbg("_set_error", f"task={task_key} error={msg}")


if __name__ == "__main__":
    # ✅ 强烈建议：用环境变量 NOTION_TOKEN，避免把 token 写死在代码里
    token = ""
    u = Upload(
        notion_token=token,
        max_workers=3,
        # 你要的默认 3/3
        max_part_retries=3,
        max_task_restarts=3,
        debug=True,
    )

    u.upload_file(
        "C:/Ruibin_Ningh/program/Notion-Files-Management-Beta/Notion-Files-Management.7z",
        "2fc644ea-d11a-8010-9665-e5fbaba0fd58",
    )
    u.upload_file(
        "C:/Ruibin_Ningh/program/Notion-Files-Management-Beta/aria2c.exe",
        "2fc644ea-d11a-8010-9665-e5fbaba0fd58",
    )

    while True:
        print(u.list_status())
        time.sleep(1)
