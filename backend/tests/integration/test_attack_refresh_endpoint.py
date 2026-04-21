"""POST /admin/attack/refresh enqueues the Dramatiq actor."""
from __future__ import annotations

import os

# Required env vars for app.config.Settings — set before any app imports run.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "x" * 48)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

pytestmark = pytest.mark.integration


def test_refresh_endpoint_returns_202(monkeypatch):
    # Stub the actor's.send so the test does not require Redis
    sent = {}

    class FakeMessage:
        message_id = "fake-msg-1"

    def fake_send(*args, **kwargs):
        sent["called"] = True
        return FakeMessage()

    from app.workers import bootstrap as bs
    monkeypatch.setattr(bs.bootstrap_attack, "send", fake_send)

    from app.routers.admin.attack import router
    from app.middleware.auth import require_admin
    from app.security.jwt import AuthUser

    app = FastAPI()
    app.include_router(router)

    # Phase 9 AUTH-02: the endpoint is guarded by Depends(require_admin).
    # This unit-ish integration test doesn't exercise the middleware chain —
    # inject a fake admin principal via dependency_overrides so the 202-path
    # under test (actor.send) runs.
    def _fake_admin() -> AuthUser:
        return AuthUser(
            id="00000000-0000-0000-0000-000000000099",
            role="Admin",
            dashboard_roles=["red", "blue"],
            jti="test-jti",
            token_version=0,
            project_memberships={},
            pm_truncated=False,
        )
    app.dependency_overrides[require_admin] = _fake_admin

    client = TestClient(app)
    resp = client.post("/admin/attack/refresh")
    assert resp.status_code == 202
    body = resp.json()
    assert body["enqueued"] is True
    assert body["message_id"] == "fake-msg-1"
    assert sent.get("called") is True
