"""下载路由：启动下载任务 + 流式取回单文件/zip。"""
import os
import anyio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..notion_facade import facade
from ..taskregistry import registry
from ..staging import new_task_dir, zip_dir
from ..deps import require_auth

router = APIRouter(prefix="/api/download", tags=["download"], dependencies=[Depends(require_auth)])


class StartIn(BaseModel):
    items: list[dict]
    page_id: str | None = None


@router.post("/start")
async def start(body: StartIn):
    save_dir = new_task_dir("download")
    h = facade.start_download(body.items, save_dir)
    h.meta["dir"] = save_dir
    return {"task_id": h.task_id}


@router.get("/{tid}/file/{idx}")
async def dl_file(tid: str, idx: int):
    h = registry.get(tid)
    if not h:
        raise HTTPException(status_code=404, detail="任务不存在")
    items = (h.progress or {}).get("items", [])
    if idx < 0 or idx >= len(items):
        raise HTTPException(status_code=404, detail="文件索引无效")
    name = items[idx].get("save_name") or items[idx].get("real_name") or items[idx].get("name") or "file"
    path = os.path.join(h.meta.get("dir", ""), os.path.basename(name))
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="文件尚未就绪")
    return FileResponse(path, filename=os.path.basename(name))


@router.get("/{tid}/zip")
async def dl_zip(tid: str):
    h = registry.get(tid)
    if not h:
        raise HTTPException(status_code=404, detail="任务不存在")
    d = h.meta.get("dir", "")
    if not os.path.isdir(d):
        raise HTTPException(status_code=404, detail="暂存目录不存在")
    zp = await anyio.to_thread.run_sync(zip_dir, d)
    return FileResponse(zp, filename=os.path.basename(zp))
