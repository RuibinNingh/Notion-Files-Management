"""流式扫描路由：下载页与工具箱「查询单个页面」共用。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..notion_facade import facade
from ..deps import require_auth

router = APIRouter(prefix="/api/scan", tags=["scan"], dependencies=[Depends(require_auth)])


class ScanIn(BaseModel):
    page_id: str
    probe_workers: int = 8


@router.post("")
async def scan(body: ScanIn):
    h = facade.start_scan(body.page_id, body.probe_workers)
    return {"task_id": h.task_id}


@router.get("/{tid}/list")
async def scan_list(tid: str):
    items = facade.read_scan_list(tid)
    return {"items": items, "count": len(items)}
