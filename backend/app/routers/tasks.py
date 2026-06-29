"""任务进度路由：SSE 事件流 + 短期 token + 取消 + 列表。

注意：``GET /{tid}/events`` 的鉴权与其它任务接口不同——它额外允许短期
``nfmsse_...`` token（``?events_token=``），所以不能挂在路由级 ``require_scope``
上，改用 ``deps.require_events_access`` 单独鉴权。其余任务接口仍需 ``tasks`` scope。
"""
import json
from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from ..taskregistry import registry
from ..deps import require_scope, require_events_access
from .. import ssetokens

# 路由级不挂统一依赖：events 走自定义鉴权，其它接口各自声明 require_scope("tasks")
router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", dependencies=[Depends(require_scope("tasks"))])
async def list_tasks():
    return registry.list()


@router.get("/{tid}", dependencies=[Depends(require_scope("tasks"))])
async def task_detail(tid: str):
    d = registry.detail(tid)
    if d is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return d


@router.post("/{tid}/events-token", dependencies=[Depends(require_scope("tasks"))])
async def events_token(tid: str):
    """签发一个短期 SSE token，供浏览器 EventSource 用 ``?events_token=`` 订阅。

    需要 session 或带 ``tasks`` scope 的 API Key（第三方不能凭空换 token）。
    token 绑定 ``tid``、10 分钟有效，进程内存储，重启失效。
    """
    # 任务不存在也允许签发？不允许——避免为不存在的 task 发 token。
    if registry.detail(tid) is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    token, expires_in = ssetokens.create(tid)
    return {"token": token, "expires_in": expires_in}


@router.get("/{tid}/events")
async def events(tid: str, _auth: bool = Depends(require_events_access)):
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


@router.post("/{tid}/cancel", dependencies=[Depends(require_scope("tasks"))])
async def cancel(tid: str):
    ok = await registry.cancel(tid)
    if not ok:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"ok": True}


@router.post("/{tid}/retry", dependencies=[Depends(require_scope("tasks"))])
async def retry(tid: str):
    try:
        h = registry.retry(tid)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not h:
        raise HTTPException(status_code=400, detail="任务不支持重试或已不存在")
    return {"task_id": h.task_id}
