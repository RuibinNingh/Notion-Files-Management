"""下载路由：启动下载任务 + 流式取回单文件/zip。"""
import os
import anyio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..notion_facade import facade
from ..taskregistry import registry
from ..staging import new_task_dir, zip_dir
from ..deps import require_scope
from url_security import UnsafeUrlError, assert_safe_remote_url

router = APIRouter(prefix="/api/download", tags=["download"], dependencies=[Depends(require_scope("download"))])


class DownloadItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    url: str = Field(min_length=1, max_length=8192)
    real_name: str | None = Field(default=None, max_length=512)
    name: str | None = Field(default=None, max_length=512)
    size_mb: float | None = Field(default=0.0, ge=0)
    block_id: str | None = Field(default=None, max_length=128)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        try:
            assert_safe_remote_url(v)
        except UnsafeUrlError as e:
            raise ValueError(str(e)) from e
        return v


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DownloadItem] = Field(min_length=1, max_length=1000)
    page_id: str | None = Field(default=None, max_length=128)


@router.post("/start")
async def start(body: StartIn):
    save_dir = new_task_dir("download")
    h = facade.start_download([it.model_dump() for it in body.items], save_dir)
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
