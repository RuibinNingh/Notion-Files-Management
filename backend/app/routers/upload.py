"""上传路由：收文件到 staging → 启动上传任务。"""
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, ConfigDict, Field

from ..notion_facade import facade
from ..staging import new_task_dir, write_cache_meta
from ..config import STAGING_DIR
from ..deps import require_auth

router = APIRouter(prefix="/api/upload", tags=["upload"], dependencies=[Depends(require_auth)])


def _sanitize(rel: str) -> str:
    rel = rel.replace("\\", "/")
    parts = [p for p in rel.split("/") if p not in ("", ".", "..")]
    return "/".join(parts)[:1024]


def _validated_upload_session(session_id: str) -> Path:
    try:
        p = Path(session_id)
        if not p.is_absolute():
            p = STAGING_DIR / session_id
        p = p.resolve()
        base = STAGING_DIR.resolve()
        p.relative_to(base)
    except Exception:
        raise HTTPException(status_code=400, detail="无效的上传会话")
    if p.parent != base or not p.name.startswith("upload-") or not p.is_dir():
        raise HTTPException(status_code=400, detail="无效的上传会话")
    return p


@router.post("/files")
async def upload_files(files: list[UploadFile] = File(...), rels: list[str] = Form(default=[])):
    session_dir = new_task_dir("upload")
    saved = []
    for i, f in enumerate(files):
        rel = _sanitize(rels[i]) if i < len(rels) else _sanitize(f.filename or f"file_{i}")
        if not rel:
            rel = f"file_{i}"
        dest = os.path.join(session_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        data = await f.read()
        with open(dest, "wb") as out:
            out.write(data)
        saved.append({"rel": rel, "size": len(data)})
    if saved:
        first = saved[0]["rel"]
        display_name = f"上传 {first}" if len(saved) == 1 else f"上传 {len(saved)} 个文件 · {first}"
        write_cache_meta(session_dir, kind="upload", display_name=display_name)
    return {"session_id": session_dir, "files": saved}


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=4096)
    folder_mode: bool = False


@router.post("/start")
async def start(body: StartIn):
    session_dir = str(_validated_upload_session(body.session_id))
    if body.folder_mode:
        manifest = []
        for root, _, fs in os.walk(session_dir):
            for fn in fs:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, session_dir).replace("\\", "/")
                manifest.append({"path": full, "rel": rel})
        h = facade.start_upload(body.page_id, [], folder_mode=True, manifest=manifest)
    else:
        paths = []
        for root, _, fs in os.walk(session_dir):
            for fn in fs:
                paths.append(os.path.join(root, fn))
        h = facade.start_upload(body.page_id, paths, folder_mode=False)
    h.meta["session_id"] = session_dir
    h.cache_refs = [session_dir]
    h.artifact = {"cache_id": os.path.basename(session_dir)}
    return {"task_id": h.task_id}
