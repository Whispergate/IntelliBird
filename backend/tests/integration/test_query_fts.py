"""Integration: FTS via /api/events?free_text=... — FIL-05.

Uses the same testcontainers + alembic pattern as test_events_api.py.
Container spins up once per module; client fixture re-seeds per test.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.fixtures.events_seed import (
    SOURCE_NVD,
    SOURCE_RSS,
    SOURCE_TAXII,
    seed_50_events,
)

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Module-scoped sync fixture: spin up container + apply schema once per file
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_db_fts():
    """Module-scoped PG+TimescaleDB container for FTS integration tests."""
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
            "REDIS_URL": "redis://localhost:1",
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


# ---------------------------------------------------------------------------
# Function-scoped async fixture: wire seeded DB + events router
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def fts_client(live_db_fts):
    """Async HTTP client wired to the seeded DB for FTS endpoint tests."""
    asyncpg_url = live_db_fts

    engine = create_async_engine(asyncpg_url, pool_pre_ping=True, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # Seed 50 events — idempotent (truncates first)
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fts_empty_query_returns_400(fts_client):
    r = await fts_client.get("/events?free_text=")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_fts_whitespace_only_returns_400(fts_client):
    r = await fts_client.get("/events?free_text=   ")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_fts_returns_ranked_results(fts_client):
    r = await fts_client.get("/events?free_text=phishing&limit=50")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) > 0
    # All returned items should contain 'phish' tokens in title or description
    for item in body["items"]:
        combined = (item.get("title") or "") + " " + (item.get("description") or "")
        assert "phish" in combined.lower(), f"non-matching item: {combined[:120]}"


@pytest.mark.asyncio
async def test_fts_cursor_paginates_without_duplicates(fts_client):
    r1 = await fts_client.get("/events?free_text=vulnerability&limit=5")
    assert r1.status_code == 200
    b1 = r1.json()
    if b1["next_cursor"] is None:
        pytest.skip("not enough vulnerability-matching events to paginate")
    r2 = await fts_client.get(
        f"/events?free_text=vulnerability&limit=5&cursor={b1['next_cursor']}"
    )
    assert r2.status_code == 200
    b2 = r2.json()
    ids1 = {e["id"] for e in b1["items"]}
    ids2 = {e["id"] for e in b2["items"]}
    assert ids1.isdisjoint(ids2), "FTS cursor produced duplicate items across pages"


@pytest.mark.asyncio
async def test_fts_respects_visibility_header(fts_client):
    r_red = await fts_client.get(
        "/events?free_text=phishing&limit=50",
        headers={"X-Dashboard-Role": "red"},
    )
    assert r_red.status_code == 200
    body = r_red.json()
    assert all(e["visibility"] != "blue_only" for e in body["items"])


@pytest.mark.asyncio
async def test_fts_respects_source_filter(fts_client):
    r = await fts_client.get(
        f"/events?free_text=phishing&source={SOURCE_TAXII}&limit=50"
    )
    assert r.status_code == 200
    body = r.json()
    assert all(e["source_id"] == str(SOURCE_TAXII) for e in body["items"])


@pytest.mark.asyncio
async def test_fts_include_total(fts_client):
    r = await fts_client.get("/events?free_text=phishing&include_total=true&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] is not None
    assert body["total"] >= len(body["items"])


@pytest.mark.asyncio
async def test_fts_invalid_cursor_returns_400(fts_client):
    r = await fts_client.get("/events?free_text=apt28&cursor=not-a-valid-fts-cursor!!")
    assert r.status_code == 400
