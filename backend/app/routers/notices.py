"""公告路由：按渠道（Status/Beta）代理到不同的服务端 endpoint。
网络优先 + 本地缓存 + 已读管理。移植自 C# NoticeService.cs。"""
import json
import anyio
import requests
from fastapi import APIRouter, Depends

from ..config import config, NOTICES_CACHE
from ..deps import require_auth

router = APIRouter(prefix="/api/notices", tags=["notices"], dependencies=[Depends(require_auth)])

# 按渠道路由到不同的公告端点
_BASE = {
    "Status": ("https://nfm.ruibin-ningh.top/notices", "http://nfm.ruibin-ningh.top/notices"),
    "Beta":   ("https://beta.nfm.ruibin-ningh.top/notices", "http://beta.nfm.ruibin-ningh.top/notices"),
}


def _fetch(path: str):
    endpoints = _BASE.get(config.channel) or _BASE["Status"]
    for base in endpoints:
        try:
            r = requests.get(f"{base}/{path}", timeout=10)
            r.raise_for_status()
            return r.text
        except Exception:
            continue
    return None


def _read_ids() -> set:
    p = NOTICES_CACHE / "read_ids.json"
    if p.exists():
        try:
            return set(json.loads(p.read_text("utf-8")))
        except Exception:
            return set()
    return set()


def _save_ids(ids: set):
    NOTICES_CACHE.mkdir(parents=True, exist_ok=True)
    (NOTICES_CACHE / "read_ids.json").write_text(json.dumps(list(ids)), "utf-8")


def _work_list():
    raw = _fetch("idx.json")
    if raw:
        NOTICES_CACHE.mkdir(parents=True, exist_ok=True)
        (NOTICES_CACHE / "idx.json").write_text(raw, "utf-8")
    else:
        p = NOTICES_CACHE / "idx.json"
        raw = p.read_text("utf-8") if p.exists() else None
    if not raw:
        return {"notices": [], "cached": False}
    try:
        idx = json.loads(raw)
    except Exception:
        return {"notices": [], "cached": False}
    ids = _read_ids()
    for n in idx.get("notices", []):
        n["unread"] = n.get("id") not in ids
    return {"notices": idx.get("notices", []), "cached": True}


def _work_one(nid: str):
    raw = _fetch(f"{nid}.md")
    if not raw:
        p = NOTICES_CACHE / f"{nid}.md"
        raw = p.read_text("utf-8") if p.exists() else "（加载失败）"
    ids = _read_ids()
    ids.add(nid)
    _save_ids(ids)
    return {"id": nid, "content": raw}


@router.get("")
async def list_notices():
    return await anyio.to_thread.run_sync(_work_list)


@router.get("/{nid}")
async def get_notice(nid: str):
    return await anyio.to_thread.run_sync(_work_one, nid)
