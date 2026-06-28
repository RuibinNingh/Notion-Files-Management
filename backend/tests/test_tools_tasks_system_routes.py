import json
from pathlib import Path

from app.config import LOG_DIR, STAGING_DIR
from app.routers import system as system_router
from app.routers import tools as tools_router
from app.staging import new_task_dir, write_cache_meta
from app.taskregistry import registry


class DummyHandle:
    def __init__(self, task_id):
        self.task_id = task_id


def test_tools_properties_and_validation(monkeypatch, authed_client):
    monkeypatch.setattr(tools_router.facade, "get_database_properties", lambda ds: {"status": "success", "id": ds})
    r = authed_client.post("/api/tools/properties", json={"data_source_id": "ds1"})
    assert r.status_code == 200
    assert r.json()["id"] == "ds1"

    r = authed_client.post("/api/tools/properties", json={"data_source_id": ""})
    assert r.status_code == 422


def test_tools_start_endpoints(monkeypatch, authed_client):
    monkeypatch.setattr(tools_router.facade, "scan_pages_for_size_property", lambda ds, prop: {"pages_without_size": []})
    monkeypatch.setattr(tools_router.facade, "start_page_size_update", lambda *args: DummyHandle("ps1"))
    monkeypatch.setattr(tools_router.facade, "start_migration", lambda *args: DummyHandle("m1"))
    monkeypatch.setattr(tools_router.facade, "start_batch_remove_suffix", lambda *args: DummyHandle("s1"))
    monkeypatch.setattr(tools_router.facade, "get_database_properties", lambda ds: {"properties": {"Name": {"type": "title"}}})

    assert authed_client.post(
        "/api/tools/page-size/scan",
        json={"data_source_id": "ds", "size_property_name": "Size"},
    ).status_code == 200

    r = authed_client.post(
        "/api/tools/page-size/start",
        json={"data_source_id": "ds", "size_property_name": "Size", "page_ids": ["p1"]},
    )
    assert r.json() == {"task_id": "ps1"}

    r = authed_client.post("/api/tools/migrate/props", json={"source_id": "src", "target_id": "tgt"})
    assert r.status_code == 200
    assert "source" in r.json() and "target" in r.json()

    r = authed_client.post(
        "/api/tools/migrate/start",
        json={"source_id": "src", "target_id": "tgt", "mapping": {"A": "B"}, "max_workers": 2},
    )
    assert r.json() == {"task_id": "m1"}

    r = authed_client.post(
        "/api/tools/suffix/start",
        json={"data_source_id": "ds", "suffix": " copy", "max_workers": 2},
    )
    assert r.json() == {"task_id": "s1"}


def test_tasks_list_detail_cancel_retry_and_sse(authed_client):
    h = registry.create(
        "unit",
        initial={"progress": 1},
        cancel_fn=lambda: None,
        retry_fn=lambda: DummyHandle("retry1"),
        retryable=True,
    )

    r = authed_client.get("/api/tasks")
    assert r.status_code == 200
    assert r.json()[0]["task_id"] == h.task_id

    r = authed_client.get(f"/api/tasks/{h.task_id}")
    assert r.status_code == 200
    assert r.json()["retryable"] is True

    r = authed_client.post(f"/api/tasks/{h.task_id}/retry")
    assert r.status_code == 200
    assert r.json() == {"task_id": "retry1"}

    r = authed_client.post(f"/api/tasks/{h.task_id}/cancel")
    assert r.status_code == 200
    assert registry.get(h.task_id).status == "cancelled"

    with authed_client.stream("GET", f"/api/tasks/{h.task_id}/events") as r:
        assert r.status_code == 200
        body = b"".join(r.iter_bytes()).decode("utf-8")
    assert "event: progress" in body
    assert "event: done" in body


def test_system_logs_cache_and_traversal(authed_client):
    log_path = LOG_DIR / "unit.log"
    log_path.write_text("line1\nline2\n", "utf-8")

    r = authed_client.get("/api/logs")
    assert r.status_code == 200
    assert any(x["name"] == "unit.log" for x in r.json()["logs"])

    r = authed_client.get("/api/logs/unit.log")
    assert r.status_code == 200
    assert r.json()["content"] == "line1\nline2\n"

    assert authed_client.get("/api/logs/..%2Fsecret").status_code == 404

    r = authed_client.post("/api/logs/download", json={"names": ["unit.log", "unit.log", "../x"]})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/zip")

    cache_dir = Path(new_task_dir("download", "Cache Name"))
    (cache_dir / "a.txt").write_text("a", "utf-8")
    write_cache_meta(cache_dir, kind="download", display_name="Cache Name")

    r = authed_client.get("/api/cache/items")
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["items"]]
    assert cache_dir.name in ids

    r = authed_client.get(f"/api/cache/items/{cache_dir.name}/download")
    assert r.status_code == 200

    assert authed_client.get("/api/cache/items/..%2Fconfig.json/download").status_code == 404

    r = authed_client.delete(f"/api/cache/items/{cache_dir.name}")
    assert r.status_code == 200
    assert not cache_dir.exists()

    generated_meta = list(STAGING_DIR.glob("generated-*.zip.meta.json"))
    for p in generated_meta:
        try:
            json.loads(p.read_text("utf-8"))
        except Exception:
            raise AssertionError(f"invalid cache metadata: {p}")


def test_system_restart_schedules_timer(monkeypatch, authed_client):
    scheduled = {}

    class DummyTimer:
        def __init__(self, delay, fn):
            scheduled["delay"] = delay
            scheduled["fn"] = fn

        def start(self):
            scheduled["started"] = True

    monkeypatch.setattr(system_router.threading, "Timer", DummyTimer)
    r = authed_client.post("/api/system/restart")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert scheduled["started"] is True
