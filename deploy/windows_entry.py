"""Windows PyInstaller entrypoint: local web console launcher.

This file is intentionally separate from docker/systemd startup. It is only used
by the Windows exe packaging path, so server deployments keep using
``uvicorn app.main:app`` or ``deploy/run.py`` unchanged.
"""
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _resolve_paths():
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        sys.path.insert(0, str(base / "backend"))
        sys.path.insert(0, str(base / "backend" / "scripts"))
        os.environ.setdefault("NFM_FRONTEND_DIST", str(base / "frontend" / "dist"))
        return

    repo = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo / "backend"))
    sys.path.insert(0, str(repo / "backend" / "scripts"))
    dist = repo / "frontend" / "dist"
    if dist.exists():
        os.environ.setdefault("NFM_FRONTEND_DIST", str(dist))


def _default_data_dir() -> str:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return str(Path(local_app_data) / "Notion-Files-Management")
    return str(Path.home() / ".notion-files-management")


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) != 0


def _pick_port(host: str, preferred: int) -> int:
    if preferred > 0 and _port_available(host, preferred):
        return preferred
    if preferred <= 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, 0))
            return int(sock.getsockname()[1])
    for port in range(preferred + 1, preferred + 50):
        if _port_available(host, port):
            return port
    raise RuntimeError(f"No available local port near {preferred}")


def _open_browser_later(url: str) -> None:
    def _worker():
        time.sleep(1.2)
        webbrowser.open(url)

    threading.Thread(target=_worker, daemon=True).start()


def main():
    _resolve_paths()
    os.environ.setdefault("NFM_DATA_DIR", _default_data_dir())
    os.environ.setdefault("NFM_SESSION_HTTPS_ONLY", "0")

    import uvicorn

    host = os.environ.get("NFM_HOST", "127.0.0.1")
    # Keep the Windows desktop launcher on the same default backend port as
    # Docker/systemd/dev. Set NFM_PORT only when a deployment needs an override.
    preferred_port = int(os.environ.get("NFM_PORT", "18765"))
    port = _pick_port(host, preferred_port)
    os.environ["NFM_PORT"] = str(port)
    url = f"http://{host}:{port}"
    data_dir = Path(os.environ["NFM_DATA_DIR"])

    print("=" * 60, flush=True)
    print("Notion Files Management Windows Console", flush=True)
    print(f"Data dir: {data_dir}", flush=True)
    print(f"Config:   {data_dir / 'config.json'}", flush=True)
    print(f"Logs:     {data_dir / 'logs'}", flush=True)
    print(f"Cache:    {data_dir / 'staging'}", flush=True)
    print(f"Open: {url}", flush=True)
    if port != preferred_port:
        print(f"Port {preferred_port} is busy; using {port}.", flush=True)
    print("=" * 60, flush=True)

    _open_browser_later(url)
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
