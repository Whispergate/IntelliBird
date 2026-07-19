"""Unit tests for admin/sources CRUD router -.

Uses httpx.AsyncClient + ASGITransport with an in-memory aiosqlite DB
backed by SQLAlchemy async engine. All 17 tests run without Postgres or Redis.
The schema is created with SQLite-compatible DDL (avoiding PG-specific JSONB,
ARRAY, UUID types that SQLite can't render).
"""
from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "a" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "b" * 64)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import uuid  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.models.sources import Source  # noqa: E402
from app.routers.admin.sources import router  # noqa: E402

# SQLite-compatible DDL for the tables we need.
# IDs are set from Python side (uuid.uuid4) - no server-side gen_random_uuid needed.
_SOURCES_DDL = """
CREATE TABLE IF NOT EXISTS sources (
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 feed_type TEXT NOT NULL,
 url TEXT NOT NULL,
 credentials_enc TEXT,
 credentials_key_version INTEGER NOT NULL DEFAULT 1,
 poll_interval_sec INTEGER NOT NULL DEFAULT 3600,
 hot_retention_days INTEGER NOT NULL DEFAULT 30,
 enabled INTEGER NOT NULL DEFAULT 1,
 last_polled_at TEXT,
 last_cursor TEXT,
 last_status TEXT,
 consecutive_failures INTEGER NOT NULL DEFAULT 0,
 archive_policy TEXT NOT NULL DEFAULT 'drop',
 silent_failure_count INTEGER NOT NULL DEFAULT 0,
 created_at TEXT DEFAULT (datetime('now'))
)
"""

_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS events (
 id TEXT PRIMARY KEY,
 stix_id TEXT,
 stix_type TEXT NOT NULL,
 source_id TEXT,
 fetched_at TEXT DEFAULT (datetime('now')) NOT NULL,
 raw_reference TEXT,
 observed_at TEXT NOT NULL,
 title TEXT,
 description TEXT,
 confidence INTEGER,
 tlp_marking_id TEXT,
 content_hash TEXT NOT NULL,
 geo_lat REAL,
 geo_lon REAL,
 country_code TEXT,
 visibility TEXT NOT NULL DEFAULT 'shared',
 raw_stix TEXT,
 tags TEXT,
 archived INTEGER NOT NULL DEFAULT 0,
 created_at TEXT DEFAULT (datetime('now'))
)
"""


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.execute(text(_SOURCES_DDL))
        await conn.execute(text(_EVENTS_DDL))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    app = FastAPI()
    app.include_router(router)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    from app.database import get_session
    from app.middleware.auth import require_admin, require_analyst_or_above, require_auth
    from app.security.jwt import AuthUser

    fake_admin = AuthUser(
        id=str(uuid.uuid4()),
        role="Admin",
        dashboard_roles=["red", "blue"],
        jti=str(uuid.uuid4()),
        token_version=0,
    )

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[require_admin] = lambda: fake_admin
    app.dependency_overrides[require_analyst_or_above] = lambda: fake_admin
    app.dependency_overrides[require_auth] = lambda: fake_admin

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _make_payload(**overrides) -> dict:
    base = {
        "name": "Test Source",
        "feed_type": "rss",
        "url": "https://example.com/feed.xml",
        "poll_interval_sec": 3600,
        "hot_retention_days": 30,
        "archive_policy": "drop",
        "enabled": True,
    }
    base.update(overrides)
    return base


def _make_source(**kwargs) -> Source:
    """Build a Source with explicit id + created_at (required for SQLite tests)."""
    defaults = {
        "id": uuid.uuid4(),
        "name": "Test Source",
        "feed_type": "rss",
        "url": "https://example.com/",
        "poll_interval_sec": 3600,
        "hot_retention_days": 30,
        "archive_policy": "drop",
        "enabled": True,
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    return Source(**defaults)


# ──────────────────────────── Tests ────────────────────────────


@pytest.mark.asyncio
async def test_list_sources_empty_returns_200_and_empty_list(client):
    resp = await client.get("/admin/sources")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_source_rss_returns_201_and_persists_fields(client, db_session):
    payload = _make_payload(
        name="Krebs RSS",
        feed_type="rss",
        archive_policy="keep",
        hot_retention_days=90,
    )
    resp = await client.post("/admin/sources", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Krebs RSS"
    assert data["feed_type"] == "rss"
    assert data["archive_policy"] == "keep"
    assert data["hot_retention_days"] == 90
    assert data["enabled"] is True
    assert "id" in data

    # Verify it's in the DB
    from sqlalchemy import select
    result = await db_session.execute(select(Source))
    rows = result.scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_create_source_nvd_with_credentials_encrypts(client, db_session):
    payload = _make_payload(
        name="NVD feed",
        feed_type="nvd",
        url="https://nvd.nist.gov/",
        credentials={"type": "apiKey", "key": "secret-key-value"},
    )
    resp = await client.post("/admin/sources", json=payload)
    assert resp.status_code == 201

    body_str = resp.text
    # credentials_enc must NOT be present in response
    assert "credentials_enc" not in body_str

    # DB must have credentials_enc set (non-null)
    from sqlalchemy import select
    result = await db_session.execute(select(Source))
    src = result.scalars().first()
    assert src is not None
    assert src.credentials_enc is not None
    assert src.credentials_enc != ""


@pytest.mark.asyncio
async def test_create_source_missing_name_returns_422(client):
    payload = _make_payload()
    del payload["name"]
    resp = await client.post("/admin/sources", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_source_invalid_feed_type_returns_422(client):
    payload = _make_payload(feed_type="bogus")
    resp = await client.post("/admin/sources", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_source_404_for_unknown_uuid(client):
    resp = await client.get(f"/admin/sources/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_source_partial_fields_preserves_others(client, db_session):
    create_resp = await client.post("/admin/sources", json=_make_payload(
        name="Original Name", enabled=True
    ))
    assert create_resp.status_code == 201
    src_id = create_resp.json()["id"]

    patch_resp = await client.patch(f"/admin/sources/{src_id}", json={"enabled": False})
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["enabled"] is False
    assert data["name"] == "Original Name"  # unchanged


@pytest.mark.asyncio
async def test_update_source_empty_credentials_preserves_existing(client, db_session):
    # Seed source with credentials_enc directly in DB
    src = _make_source(
        name="TAXII Source",
        feed_type="taxii",
        url="https://taxii.example.com/",
        credentials_enc="abc-encrypted",
    )
    db_session.add(src)
    await db_session.commit()
    await db_session.refresh(src)
    src_id = str(src.id)

    # PATCH without credentials key
    patch_resp = await client.patch(f"/admin/sources/{src_id}", json={"name": "Updated"})
    assert patch_resp.status_code == 200

    # DB credentials_enc must be unchanged
    await db_session.refresh(src)
    assert src.credentials_enc == "abc-encrypted"


@pytest.mark.asyncio
async def test_update_source_nonempty_credentials_reencrypts(client, db_session):
    src = _make_source(
        name="NVD Source",
        feed_type="nvd",
        url="https://nvd.nist.gov/",
        credentials_enc="old-encrypted-blob",
    )
    db_session.add(src)
    await db_session.commit()
    await db_session.refresh(src)
    src_id = str(src.id)

    patch_resp = await client.patch(
        f"/admin/sources/{src_id}",
        json={"credentials": {"type": "apiKey", "key": "new-key"}},
    )
    assert patch_resp.status_code == 200

    await db_session.refresh(src)
    assert src.credentials_enc != "old-encrypted-blob"
    assert src.credentials_enc is not None


@pytest.mark.asyncio
async def test_update_source_body_feed_type_ignored(client, db_session):
    src = _make_source(
        name="RSS Source",
        feed_type="rss",
        url="https://example.com/rss.xml",
    )
    db_session.add(src)
    await db_session.commit()
    await db_session.refresh(src)
    src_id = str(src.id)

    # Attempt to change feed_type (should be ignored) along with a valid field
    patch_resp = await client.patch(
        f"/admin/sources/{src_id}",
        json={"feed_type": "taxii", "name": "New Name"},
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    # feed_type unchanged
    assert data["feed_type"] == "rss"
    assert data["name"] == "New Name"


@pytest.mark.asyncio
async def test_delete_source_returns_204_and_publishes_reload(client, db_session, monkeypatch):
    calls = []

    def fake_publish(action="reload", *, deleted=None):
        calls.append({"action": action, "deleted": deleted})

    monkeypatch.setattr("app.routers.admin.sources.publish_sources_changed", fake_publish)

    create_resp = await client.post("/admin/sources", json=_make_payload(
        name="To Delete", feed_type="rss"
    ))
    assert create_resp.status_code == 201
    src_id = create_resp.json()["id"]

    # Clear calls from the create
    calls.clear()

    del_resp = await client.delete(f"/admin/sources/{src_id}")
    assert del_resp.status_code == 204

    # Must have published reload with deleted
    assert len(calls) == 1
    assert calls[0]["action"] == "reload"
    assert calls[0]["deleted"] == [{"feed_type": "rss", "source_id": src_id}]


@pytest.mark.asyncio
async def test_delete_unknown_source_404(client):
    resp = await client.delete(f"/admin/sources/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_event_count_returns_integer(client, db_session):
    # SQLite doesn't enforce FK, so we can insert events with matching source_id
    src = _make_source(name="Counted Source")
    db_session.add(src)
    await db_session.commit()
    await db_session.refresh(src)
    src_id = src.id

    now = datetime.now(timezone.utc).isoformat()
    for i in range(2):
        event_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO events (id, stix_type, source_id, observed_at, content_hash) "
                "VALUES (:id, :stix_type, :source_id, :observed_at, :content_hash)"
            ),
            {
                "id": event_id,
                "stix_type": "x-intellibird-rss",
                "source_id": str(src_id),
                "observed_at": now,
                "content_hash": f"hash{i}",
            },
        )
    await db_session.commit()

    resp = await client.get(f"/admin/sources/{src_id}/event-count")
    assert resp.status_code == 200
    assert resp.json() == {"count": 2}


@pytest.mark.asyncio
async def test_credentials_enc_never_in_response_body(client):
    payload = _make_payload(
        name="Secret Source",
        feed_type="nvd",
        credentials={"type": "apiKey", "key": "my-api-key"},
    )
    # POST
    resp = await client.post("/admin/sources", json=payload)
    assert resp.status_code == 201
    assert "credentials_enc" not in resp.text
    src_id = resp.json()["id"]

    # GET list
    list_resp = await client.get("/admin/sources")
    assert "credentials_enc" not in list_resp.text

    # GET by id
    get_resp = await client.get(f"/admin/sources/{src_id}")
    assert "credentials_enc" not in get_resp.text

    # PATCH
    patch_resp = await client.patch(f"/admin/sources/{src_id}", json={"name": "Updated"})
    assert "credentials_enc" not in patch_resp.text


@pytest.mark.asyncio
async def test_effective_status_silent_when_threshold_exceeded(client, db_session):
    src = _make_source(
        name="Silent Source",
        last_status="ok",
        silent_failure_count=5,
    )
    db_session.add(src)
    await db_session.commit()
    await db_session.refresh(src)

    resp = await client.get(f"/admin/sources/{src.id}")
    assert resp.status_code == 200
    assert resp.json()["effective_status"] == "silent"


@pytest.mark.asyncio
async def test_effective_status_ok_below_threshold(client, db_session):
    src = _make_source(
        name="OK Source",
        last_status="ok",
        silent_failure_count=4,
    )
    db_session.add(src)
    await db_session.commit()
    await db_session.refresh(src)

    resp = await client.get(f"/admin/sources/{src.id}")
    assert resp.status_code == 200
    assert resp.json()["effective_status"] == "ok"


@pytest.mark.asyncio
async def test_list_order_by_last_polled_desc_nulls_last(client, db_session):
    t1 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc)  # newer

    s1 = _make_source(name="Polled Earlier", url="https://a.com/", last_polled_at=t1)
    s2 = _make_source(name="Polled Later", url="https://b.com/", last_polled_at=t2)
    s3 = _make_source(name="Never Polled", url="https://c.com/", last_polled_at=None)
    for s in [s1, s2, s3]:
        db_session.add(s)
    await db_session.commit()

    resp = await client.get("/admin/sources")
    assert resp.status_code == 200
    names = [item["name"] for item in resp.json()]
    # s2 (later) first, s1 second, s3 (NULL) last
    assert names.index("Polled Later") < names.index("Polled Earlier")
    assert names.index("Never Polled") == len(names) - 1
