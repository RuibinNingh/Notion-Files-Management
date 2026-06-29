# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包规范：把后端 + 前端 dist 打成单文件可执行。
用法（在仓库根目录）：
  cd frontend && npm run build && cd ..
  pyinstaller deploy/nfm.spec --noconfirm
产物：dist/NOTION_FILES_MANAGEMENT_v<版本>-<渠道>.exe（Windows）
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

PROJECT_ROOT = Path(SPECPATH).resolve().parent
BACKEND_DIR = PROJECT_ROOT / "backend"
SCRIPTS_DIR = BACKEND_DIR / "scripts"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
ICON_FILE = PROJECT_ROOT / "icon.ico"

sys.path.insert(0, str(BACKEND_DIR))
from app.app_version import version_for_channel  # noqa: E402

block_cipher = None
build_version = version_for_channel(os.environ.get("NFM_CHANNEL"))
exe_name = f"NOTION_FILES_MANAGEMENT_v{build_version}"

datas = []
binaries = []
for pkg in ("fastapi", "uvicorn", "starlette", "pydantic", "pydantic_core",
            "sse_starlette", "itsdangerous", "anyio", "requests", "dotenv"):
    d, b, _ = collect_all(pkg)
    datas += d
    binaries += b

# 前端构建产物作为数据文件
datas += [(str(FRONTEND_DIST), "frontend/dist")]

hiddenimports = []
hiddenimports += collect_submodules("app")
hiddenimports += ["notion", "download", "upload", "migrate", "batch_rename",
                  "page_size_update", "logger", "scan"]

a = Analysis(
    [str(PROJECT_ROOT / "deploy" / "windows_entry.py")],
    pathex=[str(BACKEND_DIR), str(SCRIPTS_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=exe_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_FILE),
)
