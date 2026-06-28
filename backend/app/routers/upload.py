"""上传路由：收文件到 staging → 启动上传任务。"""
import os
import anyio
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from ..notion_facade import facade
from ..staging import new_task_dir, write_cache_meta
from ..deps import require_auth

router = APIRouter(prefix="/api/upload", tags=["upload"], dependencies=[Depends(require_auth)])


def _sanitize(rel: str) -> str:
    rel = rel.replace("\\", "/")
    parts = [p for p in rel.split("/") if p not in ("", ".", "..")]
    return "/".join(parts)


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
    page_id: str
    session_id: str
    folder_mode: bool = False


@router.post("/start")
async def start(body: StartIn):
    if not os.path.isdir(body.session_id):
        raise HTTPException(status_code=400, detail="无效的上传会话")
    if body.folder_mode:
        manifest = []
        for root, _, fs in os.walk(body.session_id):
            for fn in fs:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, body.session_id).replace("\\", "/")
                manifest.append({"path": full, "rel": rel})
        h = facade.start_upload(body.page_id, [], folder_mode=True, manifest=manifest)
    else:
        paths = []
        for root, _, fs in os.walk(body.session_id):
            for fn in fs:
                paths.append(os.path.join(root, fn))
        h = facade.start_upload(body.page_id, paths, folder_mode=False)
    h.meta["session_id"] = body.session_id
    h.cache_refs = [body.session_id]
    h.artifact = {"cache_id": os.path.basename(body.session_id)}
    return {"task_id": h.task_id}
