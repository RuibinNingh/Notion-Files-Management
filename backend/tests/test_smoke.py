"""最小冒烟测试：鉴权 + 配置 + 任务列表 + 未知任务 SSE 404。
需要 httpx：pip install httpx。运行：pytest backend/tests/test_smoke.py
"""
import os
import sys
import pathlib

# 让 backend 可作为包导入
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["NFM_DATA_DIR"] = "/tmp/nfm-smoke-test"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.config import config  # noqa: E402

client = TestClient(app)


def test_settings_requires_auth():
    r = client.get("/api/settings")
    assert r.status_code == 401


def test_login_wrong_password():
    r = client.post("/api/auth/login", json={"password": "wrong"})
    assert r.status_code == 401


def test_full_auth_flow():
    r = client.post("/api/auth/login", json={"password": config["password"]})
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    r = client.get("/api/auth/check")
    assert r.json()["auth"] is True

    r = client.get("/api/settings")
    assert r.status_code == 200
    assert "notion_base_url" in r.json()

    r = client.get("/api/tasks")
    assert r.status_code == 200
    assert r.json() == []

    # 未知任务 SSE 应 404
    r = client.get("/api/tasks/nonexistent/events")
    assert r.status_code == 404


def test_version_is_public():
    # /api/version 公开，未登录也应可访问（可能因网络失败但不应 401）
    r = client.get("/api/version")
    assert r.status_code == 200
