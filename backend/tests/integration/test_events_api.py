"""Integration tests — GET /api/events + /api/events/{id} against live DB.

Exercises: pagination, filters, visibility header, archived handling, 404s.
Uses testcontainers with intellibird-db:m1 image + alembic head migration.

Note: live_db_events is module-scoped (sync) to spin up the container once;
 events_client is function-scoped (async) to create a clean connection
 per test and avoid asyncio event-loop cross-contamination.
"""
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.fixtures.events_seed import (
    SOURCE_NVD,
    SOURCE_RSS,
    SOURCE_TAXII,
    seed_50_events,
)

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]

# -------------------------------------------------------------------------------
# Module-scoped sync fixture: spin up the container + apply schema ONCE per file
# -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_db_events():
    """Module-scoped PG+TimescaleDB container with alembic schema + seeded data."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("intellibird-db:m1") as pg:
        url = pg.get_connection_url()
        parsed_url = make_url(url)
        asyncpg_url = (
            f"postgresql+asyncpg://{parsed_url.username}:{parsed_url.password}"
            f"@{parsed_url.host}:{parsed_url.port}/{parsed_url.database}"
        )
        env = os.environ | {
            "DATABASE_URL": asyncpg_url,
            "SECRET_KEY": "x" * 48,
            "REDIS_URL": "redis://localhost:1",  # unreachable — fire-and-forget pub/sub
        }
        for k, v in env.items():
            os.environ[k] = v

        r = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"alembic upgrade failed: {r.stderr[:500]}")

        yield asyncpg_url


# -------------------------------------------------------------------------------
# Function-scoped async fixture: build a fresh async engine + seed per test
# Using function scope avoids asyncio event-loop lifetime mismatch.
# -------------------------------------------------------------------------------


@pytest_asyncio.fixture
async def events_client(live_db_events):
    """Async HTTP client wired to the live DB + all events routes."""
    asyncpg_url = live_db_events

    engine = create_async_engine(asyncpg_url, pool_pre_ping=True, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # Seed 50 events — seed truncates first so idempotent across test runs
    async with factory() as session:
        await seed_50_events(session)

    from app.database import get_session
    from app.routers.events import router as events_router

    test_app = FastAPI()
    test_app.include_router(events_router)

    async def override_session():
        async with factory() as s:
            yield s

    test_app.dependency_overrides[get_session] = override_session

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as c:
        yield c

    await engine.dispose()


# -------------------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_default_returns_50_events_page_1(events_client):
    r = await events_client.get("/events?limit=200")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 50
    assert body["next_cursor"] is None
    assert body["total"] is None


@pytest.mark.asyncio
async def test_cursor_paginates(events_client):
    r1 = await events_client.get("/events?limit=20")
    assert r1.status_code == 200
    b1 = r1.json()
    assert len(b1["items"]) == 20
    assert b1["next_cursor"] is not None
    r2 = await events_client.get(f"/events?limit=20&cursor={b1['next_cursor']}")
    b2 = r2.json()
    assert len(b2["items"]) == 20
    ids1 = {e["id"] for e in b1["items"]}
    ids2 = {e["id"] for e in b2["items"]}
    assert ids1.isdisjoint(ids2)


@pytest.mark.asyncio
async def test_source_filter(events_client):
    r = await events_client.get(f"/events?source={SOURCE_NVD}&limit=200")
    b = r.json()
    assert r.status_code == 200
    assert all(e["source_id"] == str(SOURCE_NVD) for e in b["items"])


@pytest.mark.asyncio
async def test_source_type_filter(events_client):
    r = await events_client.get("/events?source_type=taxii&limit=200")
    b = r.json()
    assert r.status_code == 200
    assert all(e["source_type"] == "taxii" for e in b["items"])


@pytest.mark.asyncio
async def test_tlp_filter_resolves_name_to_uuid(events_client):
    r = await events_client.get("/events?tlp=green&limit=200")
    b = r.json()
    assert r.status_code == 200
    assert len(b["items"]) > 0
    assert all(e["tlp"] == "green" for e in b["items"])


@pytest.mark.asyncio
async def test_attack_technique_filter(events_client):
    r = await events_client.get("/events?attack_technique=T1190&limit=200")
    b = r.json()
    assert r.status_code == 200
    assert len(b["items"]) >= 1
    assert all("T1190" in e["attack_techniques"] for e in b["items"])


@pytest.mark.asyncio
async def test_tag_and_semantics_null_safe(events_client):
    r = await events_client.get("/events?tag=apt28&tag=phishing&limit=200")
    b = r.json()
    assert r.status_code == 200
    for e in b["items"]:
        assert "apt28" in e["tags"] and "phishing" in e["tags"]


@pytest.mark.asyncio
async def test_visibility_no_filter_when_no_auth(events_client):
    """AUTH_ENABLED=false (no request.state.user) → all events returned.

    Updated in plan 09-05: X-Dashboard-Role header is no longer trusted.
    Visibility filtering now requires a JWT claim (dashboard_roles). When
    AUTH_ENABLED=false (as in this integration test setup), all events are
    returned regardless of any X-Dashboard-Role header sent.
    """
    r = await events_client.get("/events?limit=200", headers={"X-Dashboard-Role": "red"})
    b = r.json()
    assert r.status_code == 200
    # No filtering applied — all visibility buckets present or absent depending on seed
    # The key assertion: the header does NOT cause a 400/422/500 error
    assert isinstance(b["items"], list)


@pytest.mark.asyncio
async def test_visibility_header_has_no_effect_blue(events_client):
    """AUTH_ENABLED=false → X-Dashboard-Role=blue header has no filtering effect.

    Updated in plan 09-05: header is ignored. All events returned.
    See test_events_query_claim.py for JWT-claim-driven visibility tests (C-2).
    """
    r = await events_client.get("/events?limit=200", headers={"X-Dashboard-Role": "blue"})
    b = r.json()
    assert r.status_code == 200
    assert isinstance(b["items"], list)


@pytest.mark.asyncio
async def test_include_total_opt_in(events_client):
    r = await events_client.get("/events?include_total=true&limit=10")
    b = r.json()
    assert r.status_code == 200
    assert b["total"] == 50
    r2 = await events_client.get("/events?limit=10")
    assert r2.json()["total"] is None


@pytest.mark.asyncio
async def test_invalid_cursor_returns_400(events_client):
    r = await events_client.get("/events?cursor=not-valid-!!")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_get_event_detail_includes_raw_stix(events_client):
    r = await events_client.get("/events?limit=1")
    first_id = r.json()["items"][0]["id"]
    detail = await events_client.get(f"/events/{first_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert "raw_stix" in body


@pytest.mark.asyncio
async def test_get_event_404_on_unknown_id(events_client):
    r = await events_client.get(f"/events/{uuid.uuid4()}")
    assert r.status_code == 404
