"""任务注册表 + SSE 推送。
替代原 C# 的 DownloadSession/UploadSession 单例 + DispatcherTimer 轮询模型：
后端任务在线程池运行，轮询协程定期读取进度，diff 后推给 SSE 订阅者。
终端状态统一用 `done` 事件（data.status 区分 done/error/cancelled），
避免与 EventSource 原生 error 事件混淆。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import anyio


@dataclass
class TaskHandle:
    task_id: str
    kind: str
    title: str = ""
    source: str = ""
    status: str = "running"
    progress: dict = field(default_factory=dict)
    error: Optional[str] = None
    backend_obj: Any = None
    cancel_fn: Optional[Callable] = None
    poll_fn: Optional[Callable] = None
    retry_fn: Optional[Callable] = None
    retryable: bool = False
    terminal: bool = False
    meta: dict = field(default_factory=dict)
    input: dict = field(default_factory=dict)
    artifact: dict = field(default_factory=dict)
    cache_refs: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    _subs: list = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class TaskRegistry:
    def __init__(self):
        self._tasks: dict[str, TaskHandle] = {}
        self._loops: dict[str, asyncio.Task] = {}

    def get(self, tid: str) -> Optional[TaskHandle]:
        return self._tasks.get(tid)

    def list(self):
        return [self._summary(h) for h in self._tasks.values()]

    def _summary(self, h: TaskHandle):
        return {
            "task_id": h.task_id,
            "kind": h.kind,
            "title": h.title or h.kind,
            "source": h.source,
            "status": h.status,
            "progress": h.progress,
            "terminal": h.terminal,
            "error": h.error,
            "retryable": bool(h.retryable and h.retry_fn),
            "input": h.input,
            "artifact": h.artifact,
            "cache_refs": h.cache_refs,
            "created_at": h.created_at,
            "updated_at": h.updated_at,
            "finished_at": h.finished_at,
        }

    def create(self, kind: str, *, backend_obj=None, poll_fn=None,
               cancel_fn=None, initial=None, title: str = "", source: str = "",
               input: Optional[dict] = None, retry_fn=None, retryable: bool = False,
               artifact: Optional[dict] = None, cache_refs: Optional[list[str]] = None,
               meta: Optional[dict] = None) -> TaskHandle:
        tid = uuid.uuid4().hex[:12]
        h = TaskHandle(
            task_id=tid, kind=kind, title=title or kind, source=source,
            backend_obj=backend_obj, poll_fn=poll_fn, cancel_fn=cancel_fn,
            retry_fn=retry_fn, retryable=retryable, progress=initial or {},
            input=input or {}, artifact=artifact or {}, cache_refs=cache_refs or [],
            meta=meta or {},
        )
        self._tasks[tid] = h
        if poll_fn:
            self._loops[tid] = asyncio.create_task(self._poll_loop(h))
        return h

    def detail(self, tid: str):
        h = self._tasks.get(tid)
        if not h:
            return None
        return self._summary(h)

    async def _poll_loop(self, h: TaskHandle):
        try:
            while not h.terminal:
                data = await anyio.to_thread.run_sync(h.poll_fn)
                async with h._lock:
                    h.progress = data or {}
                    h.updated_at = time.time()
                    if (data or {}).get("done"):
                        h.terminal = True
                        h.status = (data or {}).get("status", "done")
                        h.finished_at = h.updated_at
                        if h.status == "error":
                            h.error = (data or {}).get("error")
                    await self._fanout(h, {"event": "progress", "data": data or {}})
                if h.terminal:
                    async with h._lock:
                        await self._fanout(h, {"event": "done",
                                               "data": {"status": h.status, "error": h.error}})
                    break
                await asyncio.sleep(0.4)
        except Exception as e:
            async with h._lock:
                h.terminal = True
                h.status = "error"
                h.error = str(e)
                h.updated_at = time.time()
                h.finished_at = h.updated_at
                await self._fanout(h, {"event": "done", "data": {"status": "error", "error": str(e)}})

    async def _fanout(self, h: TaskHandle, msg: dict):
        for q in list(h._subs):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    async def subscribe(self, tid: str):
        h = self._tasks.get(tid)
        if not h:
            return None
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        async with h._lock:
            h._subs.append(q)
            await q.put({"event": "progress", "data": h.progress})
            if h.terminal:
                await q.put({"event": "done", "data": {"status": h.status, "error": h.error}})
        return q

    def unsubscribe(self, tid: str, q: asyncio.Queue):
        h = self._tasks.get(tid)
        if h and q in h._subs:
            h._subs.remove(q)

    async def cancel(self, tid: str) -> bool:
        h = self._tasks.get(tid)
        if not h:
            return False
        if h.cancel_fn:
            try:
                h.cancel_fn()
            except Exception:
                pass
        h.status = "cancelled"
        h.terminal = True
        h.updated_at = time.time()
        h.finished_at = h.updated_at
        async with h._lock:
            await self._fanout(h, {"event": "done", "data": {"status": "cancelled"}})
        return True

    def retry(self, tid: str) -> Optional[TaskHandle]:
        h = self._tasks.get(tid)
        if not h or not h.retry_fn:
            return None
        return h.retry_fn()

    def active_cache_refs(self) -> set[str]:
        refs: set[str] = set()
        for h in self._tasks.values():
            if h.terminal:
                continue
            for ref in h.cache_refs:
                if ref:
                    refs.add(ref)
            for key in ("dir", "session_id"):
                ref = h.meta.get(key)
                if ref:
                    refs.add(ref)
        return refs


registry = TaskRegistry()
