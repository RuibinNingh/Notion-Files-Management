"""PyInstaller 入口：设置 sys.path + 环境变量后启动 uvicorn。
也可直接 `python deploy/run.py` 在源码树运行。"""
import os
import sys
from pathlib import Path


def _resolve_paths():
    if getattr(sys, "frozen", False):
        # PyInstaller 解压目录
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        sys.path.insert(0, str(base / "backend"))
        sys.path.insert(0, str(base / "backend" / "scripts"))
        os.environ.setdefault("NFM_FRONTEND_DIST", str(base / "frontend" / "dist"))
    else:
        # 源码树运行
        repo = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(repo / "backend"))
        sys.path.insert(0, str(repo / "backend" / "scripts"))
        dist = repo / "frontend" / "dist"
        if dist.exists():
            os.environ.setdefault("NFM_FRONTEND_DIST", str(dist))


def main():
    _resolve_paths()
    import uvicorn
    host = os.environ.get("NFM_HOST", "127.0.0.1")
    port = int(os.environ.get("NFM_PORT", "18765"))
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
