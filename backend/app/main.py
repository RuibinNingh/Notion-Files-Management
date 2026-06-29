"""FastAPI 应用入口：SessionMiddleware、路由聚合、缓存清理线程、前端静态托管。"""
import os
import platform
import sys
import time
import threading
from datetime import datetime
from pathlib import Path

# 让 backend/scripts 下的叶子模块（notion/download/upload/...）可作为顶级模块导入
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from .config import config, DATA_DIR, CONFIG_PATH, LOG_DIR, STAGING_DIR  # noqa: E402
from .app_version import BASE_VERSION, BUILD_TIME, RELEASE_TIME, version_for_channel  # noqa: E402
from logger import PythonLogger  # noqa: E402
PythonLogger.init(str(LOG_DIR))


def _log_startup_info():
    channel = config.channel
    PythonLogger.info("========== NFM STARTUP ==========")
    PythonLogger.info(f"app=Notion Files Management version={version_for_channel(channel)} base_version={BASE_VERSION} channel={channel}")
    PythonLogger.info(f"startup_time={datetime.now().astimezone().isoformat(timespec='seconds')} build_time={BUILD_TIME} release_time={RELEASE_TIME}")
    PythonLogger.info(f"python={platform.python_version()} platform={platform.platform()}")
    PythonLogger.info(f"data_dir={DATA_DIR} config_path={CONFIG_PATH} log_dir={LOG_DIR} staging_dir={STAGING_DIR}")
    PythonLogger.info(
        "config "
        f"notion_token_configured={bool(config['notion_token'])} "
        f"notion_base_url={config['notion_base_url']} "
        f"max_download_workers={config['max_download_workers']} "
        f"max_upload_workers={config['max_upload_workers']} "
        f"enable_range_download={config['enable_range_download']} "
        f"range_download_min_mb={config['range_download_min_mb']} "
        f"range_download_chunks={config['range_download_chunks']} "
        f"cache_auto_cleanup_enabled={config['cache_auto_cleanup_enabled']} "
        f"cache_ttl_seconds={config['cache_ttl_seconds']} "
        f"cache_cleanup_interval_seconds={config['cache_cleanup_interval_seconds']}"
    )
    PythonLogger.info("=================================")


_log_startup_info()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

from .routers import (  # noqa: E402
    auth, settings as settings_router, version, notices,
    scan, download, upload, tools, tasks, system, apikeys,
)
from .staging import cleanup_old_staging  # noqa: E402
from .taskregistry import registry  # noqa: E402
from .apikeys import bootstrap_preset_key  # noqa: E402
from .cors import DynamicCORSMiddleware  # noqa: E402

# 预置 API Key（来自 NFM_BOOTSTRAP_API_KEY），以 hash 落盘
bootstrap_preset_key()


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


app = FastAPI(title="Notion Files Management", version=version_for_channel(config.channel))
app.add_middleware(
    SessionMiddleware,
    secret_key=config["secret_key"],
    session_cookie="nfm_session",
    same_site="lax",
    https_only=_env_bool("NFM_SESSION_HTTPS_ONLY", False),
    max_age=24 * 60 * 60,
)

app.include_router(auth.router)
app.include_router(settings_router.router)
app.include_router(version.router)
app.include_router(notices.router)
app.include_router(scan.router)
app.include_router(download.router)
app.include_router(upload.router)
app.include_router(tools.router)
app.include_router(tasks.router)
app.include_router(system.router)
app.include_router(apikeys.router)

# 第三方开放 API 的 CORS：动态白名单中间件，常驻。
# 每次请求实时读 config["api_cors_allowed_origins"]，改设置无需重启。
# 白名单为空 = 不开放跨域；禁止 "*" / null / 带 path 的 origin（见 app/cors.py）。
# 加在 SessionMiddleware 之后（最后 add = 最外层），以便先处理 preflight。
app.add_middleware(DynamicCORSMiddleware)


def _cache_cleanup_loop():
    while True:
        try:
            if config["cache_auto_cleanup_enabled"]:
                cleanup_old_staging(config["cache_ttl_seconds"], registry.active_cache_refs())
        except Exception:
            pass
        time.sleep(max(60, int(config["cache_cleanup_interval_seconds"] or 900)))


try:
    cleanup_old_staging(config["cache_ttl_seconds"], registry.active_cache_refs())
except Exception:
    pass
if "pytest" not in sys.modules:
    threading.Thread(target=_cache_cleanup_loop, daemon=True, name="CacheCleanup").start()

# 前端构建产物目录（dev 时为仓库 frontend/dist；docker 中由 NFM_FRONTEND_DIST 指定）
DIST = Path(os.environ.get("NFM_FRONTEND_DIST", SCRIPTS_DIR.parent.parent / "frontend" / "dist"))
if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/")
async def root():
    idx = DIST / "index.html"
    if idx.exists():
        return FileResponse(idx)
    return {"name": "Notion Files Management", "docs": "/docs", "status": "frontend not built"}


@app.api_route("/{path:path}", methods=["GET"])
async def spa_fallback(path: str, request: Request):
    if path.startswith("api"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    idx = DIST / "index.html"
    if idx.exists():
        return FileResponse(idx)
    return JSONResponse({"detail": "Not Found"}, status_code=404)
