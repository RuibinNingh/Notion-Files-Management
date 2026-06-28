"""任务进度路由：SSE 事件流 + 取消 + 列表。"""
import json
from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from ..taskregistry import registry
from ..deps import require_auth

router = APIRouter(prefix="/api/tasks", tags=["tasks"], dependencies=[Depends(require_auth)])


@router.get("")
async def list_tasks():
    return registry.list()


@router.get("/{tid}")
async def task_detail(tid: str):
    d = registry.detail(tid)
    if d is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return d


@router.get("/{tid}/events")
async def events(tid: str):
    q = await registry.subscribe(tid)
    if q is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def gen():
        try:
            while True:
                msg = await q.get()
                yield {
                    "event": msg.get("event", "progress"),
                    "data": json.dumps(msg.get("data", {}), ensure_ascii=False, default=str),
                }
                if msg.get("event") == "done":
                    break
        finally:
            registry.unsubscribe(tid, q)

    return EventSourceResponse(gen())


@router.post("/{tid}/cancel")
async def cancel(tid: str):
    ok = await registry.cancel(tid)
    if not ok:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"ok": True}


@router.post("/{tid}/retry")
async def retry(tid: str):
    try:
        h = registry.retry(tid)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not h:
        raise HTTPException(status_code=400, detail="任务不支持重试或已不存在")
    return {"task_id": h.task_id}
