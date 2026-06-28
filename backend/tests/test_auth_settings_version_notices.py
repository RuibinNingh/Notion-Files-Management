from app.config import config
from app.main import app
from app.routers import notices, version
from fastapi.testclient import TestClient


def test_logout_clears_session(authed_client):
    assert authed_client.get("/api/auth/check").json()["auth"] is True
    r = authed_client.post("/api/auth/logout")
    assert r.status_code == 200
    assert authed_client.get("/api/auth/check").json()["auth"] is False


def test_settings_update_validates_ranges_and_extra_fields(authed_client):
    r = authed_client.put("/api/settings", json={"max_download_workers": 0})
    assert r.status_code == 422

    r = authed_client.put("/api/settings", json={"channel": "Beta"})
    assert r.status_code == 422

    r = authed_client.put("/api/settings", json={"notion_base_url": "http://127.0.0.1:8080"})
    assert r.status_code == 422


def test_settings_update_persists_safe_values(authed_client):
    old = config["theme_accent_color"]
    try:
        r = authed_client.put("/api/settings", json={"theme_accent_color": "#A1B2C3"})
        assert r.status_code == 200
        assert config["theme_accent_color"] == "#A1B2C3"
    finally:
        config["theme_accent_color"] = old


def test_version_public_uses_channel(monkeypatch, client):
    monkeypatch.setattr(version, "_fetch", lambda channel: {"remote": "ok", "channel_seen": channel})
    r = client.get("/api/version")
    assert r.status_code == 200
    body = r.json()
    assert body["remote"] == "ok"
    assert body["channel"] == config.channel


def test_channel_is_public(client):
    r = client.get("/api/version/channel")
    assert r.status_code == 200
    assert r.json()["channel"] == config.channel


def test_notices_require_auth_and_mark_read(monkeypatch, authed_client):
    assert TestClient(app).get("/api/notices").status_code == 401
    monkeypatch.setattr(notices, "_work_list", lambda: {"notices": [{"id": "n1"}], "cached": True})
    monkeypatch.setattr(notices, "_work_one", lambda nid: {"id": nid, "content": "hello"})

    r = authed_client.get("/api/notices")
    assert r.status_code == 200
    assert r.json()["notices"][0]["id"] == "n1"

    r = authed_client.get("/api/notices/n1")
    assert r.status_code == 200
    assert r.json() == {"id": "n1", "content": "hello"}
