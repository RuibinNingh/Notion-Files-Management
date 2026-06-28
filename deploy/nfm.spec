# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包规范：把后端 + 前端 dist 打成单文件可执行。
用法（在仓库根目录）：
  cd frontend && npm run build && cd ..
  pyinstaller deploy/nfm.spec --noconfirm
产物：dist/nfm （单文件，需 --hiddenimports 见下）
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

datas = []
binaries = []
for pkg in ("fastapi", "uvicorn", "starlette", "pydantic", "pydantic_core",
            "sse_starlette", "itsdangerous", "anyio", "requests", "dotenv"):
    d, b, _ = collect_all(pkg)
    datas += d
    binaries += b

# 前端构建产物作为数据文件
datas += [("frontend/dist", "frontend/dist")]

hiddenimports = []
hiddenimports += collect_submodules("app")
hiddenimports += ["notion", "download", "upload", "migrate", "batch_rename",
                  "page_size_update", "logger", "scan"]

a = Analysis(
    ["deploy/run.py"],
    pathex=["backend", "backend/scripts"],
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
    name="nfm",
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
)
