"""第三方开放 API / API Key 鉴权加固测试。"""
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import config
from app import apikeys, ssetokens
from app.taskregistry import registry


@pytest.fixture(autouse=True)
def restore_state():
    saved_keys = list(config["api_keys"])
    saved_cors = list(config["api_cors_allowed_origins"])
    apikeys._rate_buckets.clear()
    apikeys._last_used_write.clear()
    ssetokens.clear()
    yield
    config["api_keys"] = saved_keys
    config["api_cors_allowed_origins"] = saved_cors
    config.save()
    apikeys._rate_buckets.clear()
    apikeys._last_used_write.clear()
    ssetokens.clear()


@pytest.fixture()
def fresh():
    """未登录的全新 client（无 session cookie），用于 Bearer/匿名/SSE token 测试。"""
    return TestClient(app)


def _bearer(plaintext: str) -> dict:
    return {"Authorization": f"Bearer {plaintext}"}


def _make_key(client, **kw) -> str:
    body = {"name": kw.get("name", "t"), "scopes": kw.get("scopes", ["scan"])}
    body.update({k: v for k, v in kw.items() if k not in body})
    r = client.post("/api/apikeys", json=body)
    assert r.status_code == 200, r.text
    return r.json()["plaintext"]


def _terminal_task() -> str:
    """注册一个立即终态的任务，用于 SSE 测试（subscribe 会推一个 done）。

    不挂 poll_fn（避免在测试线程里 asyncio.create_task 无事件循环），
    直接把 handle 标记为 terminal，subscribe 会立即推 progress + done。
    """
    h = registry.create("test", poll_fn=None, title="t")
    h.terminal = True
    h.status = "done"
    h.progress = {"done": True, "status": "done"}
    return h.task_id


# ---------- 未认证 / session ----------

def test_business_endpoints_require_auth(client):
    assert client.get("/api/tasks").status_code == 401
    assert client.get("/api/settings").status_code == 401
    assert client.get("/api/scan/x/list").status_code == 401
    assert client.get("/api/apikeys").status_code == 401


def test_session_login_still_full_access(authed_client):
    assert authed_client.get("/api/settings").status_code == 200
    assert authed_client.get("/api/tasks").status_code == 200
    assert authed_client.get("/api/apikeys").status_code == 200


# ---------- 长期 API Key 永远只走 Bearer，不再接受 ?api_key= ----------

def test_query_api_key_rejected_on_normal_endpoint(authed_client, fresh):
    pt = _make_key(authed_client, name="k", scopes=["tasks"])
    # ?api_key= 不再被接受 → 401（无 session、无 Bearer）
    assert fresh.get("/api/tasks", params={"api_key": pt}).status_code == 401


def test_query_api_key_rejected_on_sse(authed_client, fresh):
    pt = _make_key(authed_client, name="k", scopes=["tasks"])
    tid = _terminal_task()
    assert fresh.get(f"/api/tasks/{tid}/events", params={"api_key": pt}).status_code == 401


# ---------- 创建 / 列表 / 明文只显一次 ----------

def test_create_returns_plaintext_once_and_list_hides_it(authed_client):
    r = authed_client.post("/api/apikeys", json={"name": "k1", "scopes": ["scan", "download"]})
    assert r.status_code == 200
    body = r.json()
    pt = body["plaintext"]
    assert pt.startswith("nfm_")
    assert "hash" not in body["key"]
    assert "plaintext" not in body["key"]
    assert body["key"]["prefix"].startswith("nfm_")
    assert len(body["key"]["prefix"]) < len(pt)

    lst = authed_client.get("/api/apikeys").json()
    for it in lst["items"]:
        assert "hash" not in it
        assert "plaintext" not in it


def test_unknown_scope_rejected_on_create(authed_client):
    r = authed_client.post("/api/apikeys", json={"name": "x", "scopes": ["scan", "bogus"]})
    assert r.status_code == 400
    assert "bogus" in r.json()["detail"]


def test_unknown_scope_rejected_on_update(authed_client):
    pt = _make_key(authed_client, name="x", scopes=["scan"])
    rec = apikeys.list_keys()[-1]
    r = authed_client.patch(f"/api/apikeys/{rec['id']}", json={"scopes": ["scan", "nope"]})
    assert r.status_code == 400


# ---------- Bearer 鉴权 + scope ----------

def test_bearer_key_with_matching_scope(authed_client, fresh):
    pt = _make_key(authed_client, name="scan-only", scopes=["scan"])
    assert fresh.get("/api/scan/nope/list", headers=_bearer(pt)).status_code == 200
    assert fresh.get("/api/tasks", headers=_bearer(pt)).status_code == 403


def test_bearer_key_high_risk_scope(authed_client, fresh):
    pt = _make_key(authed_client, name="admin", scopes=["settings", "logs", "apikeys"])
    assert fresh.get("/api/settings", headers=_bearer(pt)).status_code == 200
    assert fresh.get("/api/logs", headers=_bearer(pt)).status_code == 200
    assert fresh.get("/api/apikeys", headers=_bearer(pt)).status_code == 200


def test_invalid_disabled_expired_forged_keys_return_401(authed_client, fresh):
    assert fresh.get("/api/tasks", headers=_bearer("nfm_definitely_not_real")).status_code == 401
    assert fresh.get("/api/tasks", headers=_bearer("garbage")).status_code == 401

    pt = _make_key(authed_client, name="disabled", scopes=["tasks"])
    rec = apikeys.list_keys()[-1]
    apikeys.update_key(rec["id"], enabled=False)
    assert fresh.get("/api/tasks", headers=_bearer(pt)).status_code == 401

    pt2 = _make_key(authed_client, name="expired", scopes=["tasks"])
    rec2 = apikeys.list_keys()[-1]
    apikeys.update_key(rec2["id"], expires_at="2000-01-01T00:00:00Z")
    assert fresh.get("/api/tasks", headers=_bearer(pt2)).status_code == 401


def test_rate_limit_returns_429(authed_client, fresh):
    pt = _make_key(authed_client, name="rl", scopes=["tasks"], rate_limit_rpm=2)
    assert fresh.get("/api/tasks", headers=_bearer(pt)).status_code == 200
    assert fresh.get("/api/tasks", headers=_bearer(pt)).status_code == 200
    assert fresh.get("/api/tasks", headers=_bearer(pt)).status_code == 429


# ---------- 过期时间：清空 + UTC 存储 ----------

def test_patch_expires_at_null_clears_expiry(authed_client):
    pt = _make_key(authed_client, name="k", scopes=["tasks"])
    rec = apikeys.list_keys()[-1]
    # 先设过期
    authed_client.patch(f"/api/apikeys/{rec['id']}", json={"expires_at": "2099-01-01T00:00:00Z"})
    assert apikeys.list_keys()[-1]["expires_at"] is not None
    # 显式传 null 清空
    r = authed_client.patch(f"/api/apikeys/{rec['id']}", json={"expires_at": None})
    assert r.status_code == 200
    assert r.json()["key"]["expires_at"] is None
    assert apikeys.list_keys()[-1]["expires_at"] is None


def test_expiry_stored_as_utc_iso(authed_client):
    # 前端传 timezone-aware UTC ISO（带 Z），后端原样存为 UTC ISO
    r = authed_client.post("/api/apikeys", json={
        "name": "utc", "scopes": ["tasks"],
        "expires_at": "2099-06-29T12:00:00.000Z",
    })
    assert r.status_code == 200
    stored = apikeys.list_keys()[-1]["expires_at"]
    assert stored is not None
    assert stored.endswith("+00:00") or stored.endswith("Z")


# ---------- 更新 / 删除 ----------

def test_update_and_delete_key(authed_client, fresh):
    pt = _make_key(authed_client, name="orig", scopes=["scan"])
    rec = apikeys.list_keys()[-1]
    r = authed_client.patch(f"/api/apikeys/{rec['id']}", json={"scopes": ["tasks"]})
    assert r.status_code == 200
    assert fresh.get("/api/tasks", headers=_bearer(pt)).status_code == 200
    assert fresh.get("/api/scan/x/list", headers=_bearer(pt)).status_code == 403

    assert authed_client.delete(f"/api/apikeys/{rec['id']}").status_code == 200
    assert fresh.get("/api/tasks", headers=_bearer(pt)).status_code == 401
    assert authed_client.delete(f"/api/apikeys/{rec['id']}").status_code == 404


# ---------- SSE：events-token + events_token ----------

def test_events_token_endpoint_requires_auth(fresh):
    tid = _terminal_task()
    assert fresh.post(f"/api/tasks/{tid}/events-token").status_code == 401


def test_bearer_can_access_sse_directly(authed_client, fresh):
    pt = _make_key(authed_client, name="sse", scopes=["tasks"])
    tid = _terminal_task()
    r = fresh.get(f"/api/tasks/{tid}/events", headers=_bearer(pt))
    assert r.status_code == 200
    assert "done" in r.text  # 终态任务 subscribe 立即推 done


def test_events_token_flow_correct_task(authed_client, fresh):
    tid = _terminal_task()
    # 用 session 换短期 token
    r = authed_client.post(f"/api/tasks/{tid}/events-token")
    assert r.status_code == 200
    token = r.json()["token"]
    assert token.startswith("nfmsse_")
    assert r.json()["expires_in"] == 600
    # 用 events_token 订阅（fresh 无 session）
    r2 = fresh.get(f"/api/tasks/{tid}/events", params={"events_token": token})
    assert r2.status_code == 200
    assert "done" in r2.text


def test_events_token_wrong_task_rejected(authed_client, fresh):
    tid = _terminal_task()
    token = authed_client.post(f"/api/tasks/{tid}/events-token").json()["token"]
    # 用 tid 的 token 访问另一个不存在的 task → 401（鉴权阶段就拦，不进 subscribe）
    assert fresh.get("/api/tasks/nope/events", params={"events_token": token}).status_code == 401


def test_events_token_expired_rejected(authed_client, fresh):
    tid = _terminal_task()
    token = authed_client.post(f"/api/tasks/{tid}/events-token").json()["token"]
    ssetokens._tokens[token]["expires_at"] = time.time() - 1
    assert fresh.get(f"/api/tasks/{tid}/events", params={"events_token": token}).status_code == 401


def test_events_token_forged_rejected(fresh):
    tid = _terminal_task()
    assert fresh.get(f"/api/tasks/{tid}/events", params={"events_token": "nfmsse_fake"}).status_code == 401


# ---------- 预置 key：弱 key 拒绝，强 key 落盘去重 ----------

def test_weak_bootstrap_key_rejected(monkeypatch):
    # 缺前缀
    monkeypatch.setenv("NFM_BOOTSTRAP_API_KEY", "too_short_no_prefix")
    n0 = len(apikeys.list_keys())
    apikeys.bootstrap_preset_key()
    assert len(apikeys.list_keys()) == n0

    # 有前缀但负载过短
    monkeypatch.setenv("NFM_BOOTSTRAP_API_KEY", "nfm_short")
    apikeys.bootstrap_preset_key()
    assert len(apikeys.list_keys()) == n0


def test_strong_bootstrap_key_persists_and_dedup(monkeypatch):
    strong = "nfm_" + "a" * 40
    monkeypatch.setenv("NFM_BOOTSTRAP_API_KEY", strong)
    n0 = len(apikeys.list_keys())
    apikeys.bootstrap_preset_key()
    assert len(apikeys.list_keys()) == n0 + 1
    # 重复调用不重建
    apikeys.bootstrap_preset_key()
    assert len(apikeys.list_keys()) == n0 + 1
    # 该明文可用且全权限
    assert apikeys.verify_key(strong) is not None
    assert "apikeys" in apikeys.verify_key(strong)["scopes"]


# ---------- CORS 动态白名单 ----------

def test_cors_allows_whitelisted_origin_only():
    config["api_cors_allowed_origins"] = ["https://allowed.example.com"]
    c = TestClient(app)
    r = c.get("/api/version", headers={"Origin": "https://allowed.example.com"})
    assert r.headers.get("access-control-allow-origin") == "https://allowed.example.com"
    # 非白名单 origin 不附加 CORS 头
    r2 = c.get("/api/version", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in r2.headers


def test_cors_rejects_wildcard_null_and_path_origins():
    for bad in ["*", "null", "https://foo.com/path", "ftp://x.com"]:
        config["api_cors_allowed_origins"] = [bad]
        c = TestClient(app)
        r = c.get("/api/version", headers={"Origin": "https://foo.com"})
        assert "access-control-allow-origin" not in r.headers, f"非法 origin 被放行: {bad}"


def test_cors_preflight_only_for_whitelisted_origin():
    config["api_cors_allowed_origins"] = ["https://allowed.example.com"]
    c = TestClient(app)
    # 白名单 preflight → 200 + CORS 头
    r = c.options("/api/version", headers={
        "Origin": "https://allowed.example.com",
        "Access-Control-Request-Method": "GET",
    })
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-methods") == "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    # 非白名单 preflight → 透传，无 CORS 头（应用返回 405）
    r2 = c.options("/api/version", headers={
        "Origin": "https://evil.example.com",
        "Access-Control-Request-Method": "GET",
    })
    assert "access-control-allow-origin" not in r2.headers


def test_settings_cors_field_validates_and_persists(authed_client):
    # 非法 origin → 422
    r = authed_client.put("/api/settings", json={"api_cors_allowed_origins": ["https://foo.com/path"]})
    assert r.status_code == 422
    # 合法 origin → 200 且持久化
    old = config["api_cors_allowed_origins"]
    try:
        r = authed_client.put("/api/settings", json={"api_cors_allowed_origins": ["https://ok.example.com"]})
        assert r.status_code == 200
        assert config["api_cors_allowed_origins"] == ["https://ok.example.com"]
        # public_dict 暴露该字段
        assert "api_cors_allowed_origins" in authed_client.get("/api/settings").json()
    finally:
        config["api_cors_allowed_origins"] = old
        config.save()
