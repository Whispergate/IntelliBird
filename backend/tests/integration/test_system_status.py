"""GET /api/system/status — FND-04 shape and loopback signal."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def _app(host: str = "127.0.0.1"):
    """Build a fresh FastAPI app bound to a given HOST value."""
    os.environ["SECRET_KEY"] = "a" * 64
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://u:p@db:5432/d"
    os.environ["REDIS_URL"] = "redis://redis:6379/0"
    os.environ["HOST"] = host
    import importlib
    import app.config as cfg
    importlib.reload(cfg)
    import app.routers.system as sys_router
    importlib.reload(sys_router)
    import app.main as main
    importlib.reload(main)
    return main.app


def test_healthz_returns_ok() -> None:
    client = TestClient(_app())
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_status_shape_loopback() -> None:
    client = TestClient(_app(host="127.0.0.1"))
    r = client.get("/api/system/status")
    assert r.status_code == 200
    body = r.json()
    assert body["auth_enabled"] is False
    assert body["host"] == "127.0.0.1"
    assert body["host_loopback_only"] is True
    assert body["warning"] is None
    assert "version" in body


def test_status_warns_when_non_loopback() -> None:
    client = TestClient(_app(host="0.0.0.0"))
    r = client.get("/api/system/status")
    assert r.status_code == 200
    body = r.json()
    assert body["host_loopback_only"] is False
    assert body["warning"] is not None
    assert "NO AUTHENTICATION" in body["warning"]
