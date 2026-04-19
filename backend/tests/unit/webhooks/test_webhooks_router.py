"""Webhook CRUD router tests — schema tests unskipped by 07-01; router tests unskipped by 07-04.

Uses httpx.AsyncClient + ASGITransport with an in-memory aiosqlite DB.
SQLite-compatible DDL avoids PG-specific types (ENUM, UUID, JSONB).
All tests run without Postgres, Redis, or network access.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import AsyncIterator
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.crypto import decrypt_credentials, encrypt_credentials
from app.schemas.webhooks import WebhookCreate, WebhookResponse, WebhookUpdate

# ---------------------------------------------------------------------------
# SQLite-compatible DDL
# (SQLite has no ENUM type; TEXT columns accept any value.)
# ---------------------------------------------------------------------------

_FILTER_PRESETS_DDL = """
CREATE TABLE IF NOT EXISTS filter_presets (
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL UNIQUE,
 query_params TEXT NOT NULL DEFAULT '{}',
 created_at TEXT DEFAULT (datetime('now')),
 updated_at TEXT DEFAULT (datetime('now'))
)
"""

_WEBHOOKS_DDL = """
CREATE TABLE IF NOT EXISTS webhooks (
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL UNIQUE,
 destination_type TEXT NOT NULL,
 url TEXT NOT NULL,
 auth_enc TEXT,
 batching_window_sec INTEGER NOT NULL DEFAULT 300,
 enabled INTEGER NOT NULL DEFAULT 1,
 last_dispatch_at TEXT,
 last_delivery_at TEXT,
 last_delivery_status TEXT,
 consecutive_failures INTEGER NOT NULL DEFAULT 0,
 created_at TEXT DEFAULT (datetime('now')),
 updated_at TEXT DEFAULT (datetime('now'))
)
"""

_BINDINGS_DDL = """
CREATE TABLE IF NOT EXISTS webhook_preset_bindings (
 webhook_id TEXT NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
 preset_name TEXT NOT NULL REFERENCES filter_presets(name) ON DELETE CASCADE,
 PRIMARY KEY (webhook_id, preset_name)
)
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_fk_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.execute(text(_FILTER_PRESETS_DDL))
        await conn.execute(text(_WEBHOOKS_DDL))
        await conn.execute(text(_BINDINGS_DDL))
        # Insert a couple of well-known presets so FK constraints don't bite
        for pname in ("preset-a", "preset-b"):
            await conn.execute(
                text(
                    "INSERT OR IGNORE INTO filter_presets (id, name, query_params) "
                    "VALUES (:id, :name, '{}')"
                ),
                {"id": str(uuid.uuid4()), "name": pname},
            )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    from app.routers.admin.webhooks import router
    from app.database import get_session

    app = FastAPI()
    app.include_router(router)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _make_payload(**overrides) -> dict:
    base = {
        "name": "test-hook",
        "destination_type": "generic",
        "url": "https://example.com/hook",
        "batching_window_sec": 300,
        "enabled": True,
        "bound_preset_names": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Schema tests (unskipped by 07-01)
# ---------------------------------------------------------------------------


def test_auth_enc_round_trip():
    """encrypt_credentials → decrypt_credentials round-trip yields original dict (base64url str)."""
    blob = encrypt_credentials(settings.SECRET_KEY, {"type": "bearer", "token": "abc123"})
    assert isinstance(blob, str), f"encrypt_credentials must return str, got {type(blob)}"
    decrypted = decrypt_credentials(settings.SECRET_KEY, blob)
    assert decrypted == {"type": "bearer", "token": "abc123"}


def test_auth_enc_never_returned_in_response():
    """WebhookResponse must NOT include auth_enc or auth field (SRC-04 parallel)."""
    assert "auth_enc" not in WebhookResponse.model_fields, (
        "auth_enc must be absent from WebhookResponse (credentials never in plaintext response)"
    )
    assert "auth" not in WebhookResponse.model_fields, (
        "auth must be absent from WebhookResponse (credentials never in plaintext response)"
    )


def test_feed_type_locked_on_update():
    """WebhookUpdate must NOT include destination_type field (locked on edit —)."""
    assert "destination_type" not in WebhookUpdate.model_fields, (
        "destination_type must be absent from WebhookUpdate (locked on edit per D-35)"
    )


# ---------------------------------------------------------------------------
# Router tests (unskipped by 07-04)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_webhooks_returns_empty(client):
    resp = await client.get("/admin/webhooks")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_webhook_encrypts_auth(client, db_session):
    payload = _make_payload(
        name="bearer-hook",
        auth={"type": "bearer", "token": "xyz"},
    )
    resp = await client.post("/admin/webhooks", json=payload)
    assert resp.status_code == 201

    # auth_enc and auth must NOT appear in response body
    body_str = resp.text
    assert "auth_enc" not in body_str
    assert "token" not in body_str

    # DB must have auth_enc non-null and round-trippable
    row = await db_session.execute(text("SELECT auth_enc FROM webhooks WHERE name='bearer-hook'"))
    auth_enc = row.scalar_one()
    assert auth_enc is not None
    decrypted = decrypt_credentials(settings.SECRET_KEY, auth_enc)
    assert decrypted == {"type": "bearer", "token": "xyz"}


@pytest.mark.asyncio
async def test_update_webhook_keeps_existing_auth_on_null(client, db_session):
    # Create with auth
    create_resp = await client.post(
        "/admin/webhooks",
        json=_make_payload(name="auth-hook", auth={"type": "bearer", "token": "keep-me"}),
    )
    assert create_resp.status_code == 201
    hook_id = create_resp.json()["id"]

    # SQLite UUID(as_uuid=True) stores UUIDs without dashes — use REPLACE to normalise
    hook_id_nohyphen = hook_id.replace("-", "")

    # Fetch original auth_enc
    row = await db_session.execute(
        text("SELECT auth_enc FROM webhooks WHERE REPLACE(id,'-','')=:id"),
        {"id": hook_id_nohyphen},
    )
    original_enc = row.scalar_one()
    assert original_enc is not None

    # PATCH without auth field — auth_enc must remain unchanged
    patch_resp = await client.patch(f"/admin/webhooks/{hook_id}", json={"enabled": False})
    assert patch_resp.status_code == 200

    db_session.expire_all()
    row2 = await db_session.execute(
        text("SELECT auth_enc FROM webhooks WHERE REPLACE(id,'-','')=:id"),
        {"id": hook_id_nohyphen},
    )
    assert row2.scalar_one() == original_enc

    # PATCH with clear_auth=True → auth_enc must become NULL
    clear_resp = await client.patch(f"/admin/webhooks/{hook_id}", json={"clear_auth": True})
    assert clear_resp.status_code == 200

    db_session.expire_all()
    row3 = await db_session.execute(
        text("SELECT auth_enc FROM webhooks WHERE REPLACE(id,'-','')=:id"),
        {"id": hook_id_nohyphen},
    )
    assert row3.scalar_one() is None


@pytest.mark.asyncio
async def test_delete_webhook_cascades_bindings(client, db_session):
    # Create webhook with 2 bindings
    create_resp = await client.post(
        "/admin/webhooks",
        json=_make_payload(name="del-hook", bound_preset_names=["preset-a", "preset-b"]),
    )
    assert create_resp.status_code == 201
    hook_id = create_resp.json()["id"]

    # SQLite's UUID(as_uuid=True) stores UUIDs without dashes — strip for raw queries
    hook_id_nohyphen = hook_id.replace("-", "")

    # Verify 2 binding rows exist (SQLite stores UUID without hyphens)
    cnt = await db_session.execute(
        text("SELECT COUNT(*) FROM webhook_preset_bindings WHERE REPLACE(webhook_id,'-','')=:id"),
        {"id": hook_id_nohyphen},
    )
    assert cnt.scalar_one() == 2

    # DELETE webhook
    del_resp = await client.delete(f"/admin/webhooks/{hook_id}")
    assert del_resp.status_code == 204

    # Bindings should be gone (CASCADE)
    db_session.expire_all()
    cnt2 = await db_session.execute(
        text("SELECT COUNT(*) FROM webhook_preset_bindings WHERE REPLACE(webhook_id,'-','')=:id"),
        {"id": hook_id_nohyphen},
    )
    assert cnt2.scalar_one() == 0


@pytest.mark.asyncio
async def test_test_send_returns_200_on_ok(monkeypatch):
    """Mock httpx to return 204 → response HTTP 200, body.ok == True."""
    from app.routers.admin import webhooks as wh_module

    class FakeResponse:
        status_code = 204

    class FakeClient:
        def __init__(self, **_kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def post(self, *_a, **_kw):
            return FakeResponse()

    monkeypatch.setattr(wh_module.httpx, "Client", FakeClient)

    from app.routers.admin.webhooks import router
    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/admin/webhooks/test-send",
            json={"destination_type": "generic", "url": "https://example.com/hook"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_test_send_returns_200_on_failure(monkeypatch):
    """Mock httpx raising ConnectError → HTTP 200, body.ok == False, error_detail set."""
    from app.routers.admin import webhooks as wh_module

    class FakeClient:
        def __init__(self, **_kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def post(self, *_a, **_kw):
            raise wh_module.httpx.ConnectError("connection refused")

    monkeypatch.setattr(wh_module.httpx, "Client", FakeClient)

    from app.routers.admin.webhooks import router
    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/admin/webhooks/test-send",
            json={"destination_type": "slack", "url": "https://hooks.slack.com/fake"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error_detail"]  # truthy


@pytest.mark.asyncio
async def test_bind_presets_persists_join_rows(client, db_session):
    resp = await client.post(
        "/admin/webhooks",
        json=_make_payload(name="bound-hook", bound_preset_names=["preset-a", "preset-b"]),
    )
    assert resp.status_code == 201
    hook_id = resp.json()["id"]

    # SQLite UUID(as_uuid=True) stores UUIDs without dashes — use REPLACE to normalise
    hook_id_nohyphen = hook_id.replace("-", "")
    cnt = await db_session.execute(
        text("SELECT COUNT(*) FROM webhook_preset_bindings WHERE REPLACE(webhook_id,'-','')=:id"),
        {"id": hook_id_nohyphen},
    )
    assert cnt.scalar_one() == 2


@pytest.mark.asyncio
async def test_list_includes_bound_preset_names(client):
    create_resp = await client.post(
        "/admin/webhooks",
        json=_make_payload(name="listed-hook", bound_preset_names=["preset-a", "preset-b"]),
    )
    assert create_resp.status_code == 201

    list_resp = await client.get("/admin/webhooks")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    names = sorted(items[0]["bound_preset_names"])
    assert names == ["preset-a", "preset-b"]
