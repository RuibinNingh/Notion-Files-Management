"""工具箱路由：页面大小更新/查询、数据源迁移、批量去后缀、属性查询。"""
import anyio
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..notion_facade import facade
from ..deps import require_auth

router = APIRouter(prefix="/api/tools", tags=["tools"], dependencies=[Depends(require_auth)])


class DsIn(BaseModel):
    data_source_id: str


@router.post("/properties")
async def properties(body: DsIn):
    return await anyio.to_thread.run_sync(facade.get_database_properties, body.data_source_id)


# ---------- 页面大小自动更新 ----------
class PageSizeScanIn(BaseModel):
    data_source_id: str
    size_property_name: str


@router.post("/page-size/scan")
async def page_size_scan(body: PageSizeScanIn):
    return await anyio.to_thread.run_sync(
        facade.scan_pages_for_size_property, body.data_source_id, body.size_property_name
    )


class PageSizeStartIn(BaseModel):
    data_source_id: str
    size_property_name: str
    page_ids: list[str]
    link_workers: int = 3
    size_workers: int = 5


@router.post("/page-size/start")
async def page_size_start(body: PageSizeStartIn):
    h = facade.start_page_size_update(
        body.data_source_id, body.size_property_name, body.page_ids,
        body.link_workers, body.size_workers,
    )
    return {"task_id": h.task_id}


# ---------- 数据源迁移 ----------
class MigratePropsIn(BaseModel):
    source_id: str
    target_id: str


@router.post("/migrate/props")
async def migrate_props(body: MigratePropsIn):
    src = await anyio.to_thread.run_sync(facade.get_database_properties, body.source_id)
    tgt = await anyio.to_thread.run_sync(facade.get_database_properties, body.target_id)
    return {"source": src, "target": tgt}


class MigrateStartIn(BaseModel):
    source_id: str
    target_id: str
    mapping: dict
    max_workers: int = 3


@router.post("/migrate/start")
async def migrate_start(body: MigrateStartIn):
    h = facade.start_migration(body.source_id, body.target_id, body.mapping, body.max_workers)
    return {"task_id": h.task_id}


# ---------- 批量去后缀 ----------
class SuffixStartIn(BaseModel):
    data_source_id: str
    suffix: str
    max_workers: int = 3


@router.post("/suffix/start")
async def suffix_start(body: SuffixStartIn):
    h = facade.start_batch_remove_suffix(body.data_source_id, body.suffix, body.max_workers)
    return {"task_id": h.task_id}
