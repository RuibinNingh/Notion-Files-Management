"""流式扫描路由：下载页与工具箱「查询单个页面」共用。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ..notion_facade import facade
from ..deps import require_scope

router = APIRouter(prefix="/api/scan", tags=["scan"], dependencies=[Depends(require_scope("scan"))])


class ScanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_id: str = Field(min_length=1, max_length=128)
    probe_workers: int = Field(default=8, ge=1, le=16)


@router.post("")
async def scan(body: ScanIn):
    h = facade.start_scan(body.page_id, body.probe_workers)
    return {"task_id": h.task_id}


@router.get("/{tid}/list")
async def scan_list(tid: str):
    items = facade.read_scan_list(tid)
    return {"items": items, "count": len(items)}
