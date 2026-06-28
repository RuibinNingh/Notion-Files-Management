from pathlib import Path

from app.config import STAGING_DIR
from app.routers import download as download_router
from app.routers import scan as scan_router
from app.routers import upload as upload_router
from app.staging import new_task_dir
from app.taskregistry import registry


class DummyHandle:
    def __init__(self, task_id="tid123"):
        self.task_id = task_id
        self.meta = {}
        self.cache_refs = []
        self.artifact = {}


def test_scan_start_and_list(monkeypatch, authed_client):
    monkeypatch.setattr(scan_router.facade, "start_scan", lambda page_id, workers: DummyHandle("scan1"))
    monkeypatch.setattr(scan_router.facade, "read_scan_list", lambda tid: [{"url": "https://example.com/a"}])

    r = authed_client.post("/api/scan", json={"page_id": "page", "probe_workers": 2})
    assert r.status_code == 200
    assert r.json() == {"task_id": "scan1"}

    assert authed_client.post("/api/scan", json={"page_id": "page", "probe_workers": 99}).status_code == 422

    r = authed_client.get("/api/scan/scan1/list")
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_download_start_rejects_private_url(authed_client):
    r = authed_client.post(
        "/api/download/start",
        json={"items": [{"url": "http://127.0.0.1/latest/meta-data", "name": "x"}]},
    )
    assert r.status_code == 422


def test_download_start_accepts_safe_url(monkeypatch, authed_client):
    captured = {}

    def fake_start(items, save_dir):
        captured["items"] = items
        captured["save_dir"] = save_dir
        return DummyHandle("download1")

    monkeypatch.setattr(download_router.facade, "start_download", fake_start)
    r = authed_client.post(
        "/api/download/start",
        json={"items": [{"url": "https://example.com/file.txt", "real_name": "file.txt"}]},
    )
    assert r.status_code == 200
    assert r.json() == {"task_id": "download1"}
    assert captured["items"][0]["url"] == "https://example.com/file.txt"


def test_download_file_and_zip_are_limited_to_task_dir(authed_client):
    d = Path(new_task_dir("download"))
    (d / "safe.txt").write_text("ok", "utf-8")
    h = registry.create("download", initial={"items": [{"save_name": "safe.txt"}]}, meta={"dir": str(d)})

    r = authed_client.get(f"/api/download/{h.task_id}/file/0")
    assert r.status_code == 200
    assert r.content == b"ok"

    r = authed_client.get(f"/api/download/{h.task_id}/file/9")
    assert r.status_code == 404

    r = authed_client.get(f"/api/download/{h.task_id}/zip")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/zip")


def test_upload_files_sanitizes_relative_paths(authed_client):
    r = authed_client.post(
        "/api/upload/files",
        files=[("files", ("evil.txt", b"data", "text/plain"))],
        data={"rels": "../nested/../../safe.txt"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["files"][0]["rel"] == "nested/safe.txt"
    assert Path(body["session_id"]).resolve().parent == STAGING_DIR.resolve()


def test_upload_start_rejects_arbitrary_directory(authed_client, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", "utf-8")

    r = authed_client.post("/api/upload/start", json={"page_id": "page", "session_id": str(outside)})
    assert r.status_code == 400


def test_upload_start_uses_valid_staging_session(monkeypatch, authed_client):
    session_dir = Path(new_task_dir("upload"))
    (session_dir / "a.txt").write_text("a", "utf-8")

    def fake_start_upload(page_id, file_paths, folder_mode=False, manifest=None):
        h = DummyHandle("upload1")
        h.input = {
            "page_id": page_id,
            "file_paths": file_paths,
            "folder_mode": folder_mode,
            "manifest": manifest,
        }
        return h

    monkeypatch.setattr(upload_router.facade, "start_upload", fake_start_upload)
    r = authed_client.post(
        "/api/upload/start",
        json={"page_id": "page", "session_id": str(session_dir), "folder_mode": False},
    )
    assert r.status_code == 200
    assert r.json() == {"task_id": "upload1"}
