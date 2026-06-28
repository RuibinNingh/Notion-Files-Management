"""系统路由：日志列表/内容/下载、清缓存、重启。"""
import sys
import threading
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from ..staging import (
    list_logs, clear_all_cache, cleanup_old_staging,
    list_cache_items, cache_item_path, delete_cache_item, zip_dir,
    log_file_path, read_log_tail, zip_logs,
)
from ..taskregistry import registry
from ..config import config
from ..deps import require_auth

router = APIRouter(prefix="/api", tags=["system"], dependencies=[Depends(require_auth)])


@router.get("/logs")
async def logs():
    """日志文件列表（不含内容）。"""
    return {"logs": list_logs()}


@router.get("/logs/{name}")
async def log_content(name: str, max_lines: int = Query(2000, ge=1, le=20000)):
    """读取单个日志文件内容（大文件只返回尾部，避免撑爆内存）。"""
    try:
        content, truncated, size = read_log_tail(name, max_lines)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="日志文件不存在")
    return {"name": name, "content": content, "truncated": truncated, "size": size}


@router.get("/logs/{name}/download")
async def log_download(name: str):
    """下载单个日志文件（原始文件，不截断）。"""
    try:
        p = log_file_path(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="日志文件不存在")
    return FileResponse(str(p), filename=name, media_type="text/plain")


@router.post("/logs/download")
async def logs_zip(body: dict):
    """多选日志打包成 zip 下载。body: {"names": ["a.logs", "b.logs"]}"""
    names = body.get("names") if isinstance(body, dict) else None
    if not isinstance(names, list) or not names:
        raise HTTPException(status_code=400, detail="未选择日志文件")
    # 去重，保序
    seen = set()
    names = [n for n in names if n and not (n in seen or seen.add(n))]
    zp = zip_logs(names)
    return FileResponse(zp, filename="nfm-logs.zip", media_type="application/zip")


@router.post("/cache/clear")
async def cache_clear():
    n = clear_all_cache(registry.active_cache_refs())
    return {"deleted": n}


@router.get("/cache/items")
async def cache_items():
    return {
        "items": list_cache_items(registry.active_cache_refs()),
        "ttl_seconds": config["cache_ttl_seconds"],
        "auto_cleanup_enabled": config["cache_auto_cleanup_enabled"],
        "cleanup_interval_seconds": config["cache_cleanup_interval_seconds"],
    }


@router.get("/cache/items/{cache_id}/download")
async def cache_download(cache_id: str):
    try:
        p = cache_item_path(cache_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="缓存不存在")
    if p.is_dir():
        zp = zip_dir(str(p))
        return FileResponse(zp, filename=f"{p.name}.zip", media_type="application/zip")
    return FileResponse(str(p), filename=p.name)


@router.delete("/cache/items/{cache_id}")
async def cache_delete(cache_id: str):
    try:
        ok = delete_cache_item(cache_id, registry.active_cache_refs())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="缓存不存在")
    if not ok:
        raise HTTPException(status_code=409, detail="缓存正在被运行中的任务使用")
    return {"ok": True}


@router.post("/cache/cleanup")
async def cache_cleanup():
    n = cleanup_old_staging(config["cache_ttl_seconds"], registry.active_cache_refs())
    return {"deleted": n}


@router.post("/system/restart")
async def restart():
    """重启进程：依赖外部进程管理器（docker/systemd）拉起新实例。"""
    def _do():
        try:
            import os
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception:
            os._exit(0)
    threading.Timer(0.2, _do).start()
    return {"ok": True}
