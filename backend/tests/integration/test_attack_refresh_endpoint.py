"""POST /admin/attack/refresh enqueues the Dramatiq actor."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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
    app = FastAPI()
    app.include_router(router)

    client = TestClient(app)
    resp = client.post("/admin/attack/refresh")
    assert resp.status_code == 202
    body = resp.json()
    assert body["enqueued"] is True
    assert body["message_id"] == "fake-msg-1"
    assert sent.get("called") is True
