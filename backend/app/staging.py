"""临时文件管理：下载暂存目录 + zip 打包 + 缓存清理 + 日志列表。"""
import os
import shutil
import time
import uuid
import zipfile
import json
from collections import deque
from pathlib import Path

from .config import DATA_DIR, LOG_DIR, STAGING_DIR, NOTICES_CACHE

CACHE_META_NAME = ".nfm-cache.json"


def new_task_dir(kind: str = "task", display_name: str | None = None) -> str:
    safe = "".join(ch for ch in kind if ch.isalnum() or ch in ("-", "_")).strip("-_") or "task"
    d = os.path.join(str(STAGING_DIR), f"{safe}-{uuid.uuid4().hex[:12]}")
    os.makedirs(d, exist_ok=True)
    if display_name:
        write_cache_meta(d, kind=kind, display_name=display_name)
    return d


def zip_dir(dir_path: str) -> str:
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    zp = os.path.join(str(STAGING_DIR), f"generated-{os.path.basename(dir_path)}.zip")
    source_meta = read_cache_meta(dir_path)
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(dir_path):
            for f in files:
                if f == CACHE_META_NAME:
                    continue
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, dir_path))
    display = source_meta.get("display_name") or os.path.basename(dir_path)
    write_cache_meta(zp, kind="generated", display_name=f"打包 {display}")
    return zp


def _meta_path(path: str | Path) -> Path:
    p = Path(path)
    if p.is_dir() or (not p.exists() and not p.suffix):
        return p / CACHE_META_NAME
    return p.with_name(p.name + ".meta.json")


def write_cache_meta(path: str | Path, **meta) -> None:
    try:
        p = _meta_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        old = {}
        if p.exists():
            try:
                old = json.loads(p.read_text("utf-8"))
            except Exception:
                old = {}
        old.update({k: v for k, v in meta.items() if v is not None})
        old["updated_at"] = time.time()
        p.write_text(json.dumps(old, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass


def read_cache_meta(path: str | Path) -> dict:
    try:
        p = _meta_path(path)
        if p.exists():
            return json.loads(p.read_text("utf-8"))
    except Exception:
        pass
    return {}


def _path_size(path: str) -> tuple[int, int]:
    if os.path.isfile(path):
        return os.path.getsize(path), 1
    total = 0
    files = 0
    for root, _, names in os.walk(path):
        for name in names:
            if name == CACHE_META_NAME or name.endswith(".meta.json"):
                continue
            full = os.path.join(root, name)
            try:
                total += os.path.getsize(full)
                files += 1
            except OSError:
                pass
    return total, files


def _cache_kind(name: str, is_dir: bool) -> str:
    if name.startswith("upload-"):
        return "upload"
    if name.startswith("download-"):
        return "download"
    if name.startswith("generated-") or name.startswith("logs-") or name.endswith(".zip"):
        return "generated"
    if is_dir:
        return "unknown"
    return "generated"


def _safe_staging_child(cache_id: str) -> Path:
    base = STAGING_DIR.resolve()
    p = (STAGING_DIR / cache_id).resolve()
    try:
        p.relative_to(base)
    except ValueError:
        raise FileNotFoundError(cache_id)
    if p.parent != base:
        raise FileNotFoundError(cache_id)
    if not p.exists():
        raise FileNotFoundError(cache_id)
    return p


def list_cache_items(protected_paths: set[str] | None = None) -> list[dict]:
    protected = {str(Path(p).resolve()) for p in (protected_paths or set()) if p}
    out = []
    if not STAGING_DIR.is_dir():
        return out
    for name in sorted(os.listdir(str(STAGING_DIR))):
        try:
            if name == CACHE_META_NAME or name.endswith(".meta.json"):
                continue
            p = _safe_staging_child(name)
            meta = read_cache_meta(p)
            st = p.stat()
            size, files = _path_size(str(p))
            resolved = str(p.resolve())
            busy = resolved in protected
            display_name = meta.get("display_name") or name
            out.append({
                "id": name,
                "name": display_name,
                "storage_name": name,
                "kind": meta.get("kind") or _cache_kind(name, p.is_dir()),
                "path": str(p),
                "is_dir": p.is_dir(),
                "size": size,
                "files": files,
                "created_at": st.st_ctime,
                "updated_at": st.st_mtime,
                "age_seconds": max(0, int(time.time() - st.st_mtime)),
                "busy": busy,
            })
        except Exception:
            continue
    out.sort(key=lambda x: x["updated_at"], reverse=True)
    return out


def cache_item_path(cache_id: str) -> Path:
    return _safe_staging_child(cache_id)


def delete_cache_item(cache_id: str, protected_paths: set[str] | None = None) -> bool:
    p = _safe_staging_child(cache_id)
    protected = {str(Path(x).resolve()) for x in (protected_paths or set()) if x}
    if str(p.resolve()) in protected:
        return False
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    else:
        p.unlink(missing_ok=True)
        try:
            _meta_path(p).unlink(missing_ok=True)
        except Exception:
            pass
    return True


def cleanup_old_staging(max_age_seconds: int = 3600, protected_paths: set[str] | None = None) -> int:
    now = time.time()
    n = 0
    protected = {str(Path(p).resolve()) for p in (protected_paths or set()) if p}
    if os.path.isdir(str(STAGING_DIR)):
        for name in os.listdir(str(STAGING_DIR)):
            p = os.path.join(str(STAGING_DIR), name)
            try:
                if str(Path(p).resolve()) in protected:
                    continue
                if os.path.getmtime(p) < now - max_age_seconds:
                    if os.path.isdir(p):
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        os.remove(p)
                        try:
                            _meta_path(p).unlink(missing_ok=True)
                        except Exception:
                            pass
                    n += 1
            except Exception:
                pass
    return n


def clear_all_cache(protected_paths: set[str] | None = None) -> int:
    """清除 staging / 公告缓存（对应原 ToolsPage「清除一切缓存」）。"""
    n = 0
    protected = {str(Path(p).resolve()) for p in (protected_paths or set()) if p}
    for sub in ("staging", str(NOTICES_CACHE.name)):
        p = os.path.join(str(DATA_DIR), sub) if sub != NOTICES_CACHE.name else str(NOTICES_CACHE)
        if os.path.isdir(p):
            if sub == "staging" and protected:
                for name in os.listdir(p):
                    child = os.path.join(p, name)
                    try:
                        if str(Path(child).resolve()) in protected:
                            continue
                        if os.path.isdir(child):
                            shutil.rmtree(child, ignore_errors=True)
                        else:
                            os.remove(child)
                        n += 1
                    except Exception:
                        pass
            else:
                shutil.rmtree(p, ignore_errors=True)
                n += 1
    return n


def list_logs() -> list:
    out = []
    if os.path.isdir(str(LOG_DIR)):
        for name in sorted(os.listdir(str(LOG_DIR))):
            full = os.path.join(str(LOG_DIR), name)
            if os.path.isfile(full):
                out.append({"name": name, "size": os.path.getsize(full)})
    return out


def log_file_path(name: str) -> Path:
    """返回 LOG_DIR 直属文件的安全路径;非法(目录穿越/子目录)或不存在则 raise FileNotFoundError。"""
    base = LOG_DIR.resolve()
    p = (LOG_DIR / name).resolve()
    try:
        p.relative_to(base)
    except ValueError:
        raise FileNotFoundError(name)
    if p.parent != base:  # 禁止任何子目录
        raise FileNotFoundError(name)
    if not p.is_file():
        raise FileNotFoundError(name)
    return p


def read_log_tail(name: str, max_lines: int = 2000) -> tuple:
    """读取日志文件(>1MB 或超 max_lines 行时只返回尾部)。
    返回 (content, truncated, size_bytes)。"""
    p = log_file_path(name)
    size = p.stat().st_size
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        if size > 1024 * 1024:  # >1MB:只读尾部 max_lines 行,避免撑爆内存
            content = "".join(deque(f, maxlen=max_lines))
            return content, True, size
        content = f.read()
    lines = content.splitlines()
    if len(lines) > max_lines:
        content = "\n".join(lines[-max_lines:])
        return content, True, size
    return content, False, size


def zip_logs(names) -> str:
    """把多个日志文件打包成 zip(跳过非法/不存在的),返回 zip 路径(落 STAGING_DIR,由 TTL 清理)。"""
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    zp = STAGING_DIR / f"logs-{uuid.uuid4().hex[:8]}.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for name in names:
            try:
                p = log_file_path(name)
            except FileNotFoundError:
                continue
            z.write(p, name)
    return str(zp)
