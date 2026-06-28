import os
import pathlib
import sys

import pytest
from fastapi.testclient import TestClient


ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "scripts"))
os.environ.setdefault("NFM_DATA_DIR", "/tmp/nfm-pytest")

from app.config import LOG_DIR, STAGING_DIR, config  # noqa: E402
from app.main import app  # noqa: E402
from app.taskregistry import registry  # noqa: E402


@pytest.fixture(autouse=True)
def clean_registry():
    registry._tasks.clear()
    registry._loops.clear()
    yield
    registry._tasks.clear()
    registry._loops.clear()


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def authed_client(client):
    r = client.post("/api/auth/login", json={"password": config["password"]})
    assert r.status_code == 200
    return client


@pytest.fixture(autouse=True)
def ensure_dirs():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
