"""Integration: PATCH /api/events/{id}/tags - FIL-03 live DB.

Uses testcontainers with intellibird-db:m1 image + alembic head migration.
Follows the pattern established in test_events_api.py: module-scoped container,
function-scoped async engine per test to avoid asyncio event-loop mismatch.
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
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.fixtures.events_seed import (
    seed_50_events,
)

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Module-scoped sync fixture: spin up DB container + apply schema ONCE
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_db_tags():
    """Module-scoped PG+TimescaleDB container with alembic schema."""
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
            "JWT_SIGNING_KEY": "j" * 64,
            "REDIS_URL": "redis://localhost:1",  # unreachable - not needed for these tests
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
# Function-scoped async fixture: fresh engine + tags router + seeded data
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def tags_client(live_db_tags):
    """Async HTTP client wired to the live DB with tags + events routes."""
    asyncpg_url = live_db_tags

    engine = create_async_engine(asyncpg_url, pool_pre_ping=True, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # Seed 50 events - idempotent (truncates first)
    async with factory() as session:
        await seed_50_events(session)

    from app.database import get_session
    from app.routers.events import router as events_router
    from app.routers.tags import router as tags_router

    test_app = FastAPI()
    # Mount both events (for GET /api/events/{id}) and tags router under /api
    test_app.include_router(events_router, prefix="/api")
    test_app.include_router(tags_router, prefix="/api")

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
async def test_patch_adds_tags_persists(tags_client):
    """PATCH add → tag appears in response + persists on GET /api/events/{id}."""
    # Get first event from list
    r_list = await tags_client.get("/api/events?limit=1")
    assert r_list.status_code == 200
    eid = r_list.json()["items"][0]["id"]

    r = await tags_client.patch(
        f"/api/events/{eid}/tags",
        json={"add": ["integ-new-tag-a"], "remove": []},
    )
    assert r.status_code == 200
    assert "integ-new-tag-a" in r.json()["tags"]

    # Confirm persistence via detail endpoint
    d = await tags_client.get(f"/api/events/{eid}")
    assert d.status_code == 200
    assert "integ-new-tag-a" in d.json()["tags"]


@pytest.mark.asyncio
async def test_patch_removes_tags(tags_client):
    """PATCH add then remove → tag is absent from response."""
    r_list = await tags_client.get("/api/events?limit=1")
    eid = r_list.json()["items"][0]["id"]

    await tags_client.patch(
        f"/api/events/{eid}/tags",
        json={"add": ["integ-to-remove"], "remove": []},
    )
    r = await tags_client.patch(
        f"/api/events/{eid}/tags",
        json={"add": [], "remove": ["integ-to-remove"]},
    )
    assert r.status_code == 200
    assert "integ-to-remove" not in r.json()["tags"]


@pytest.mark.asyncio
async def test_patch_idempotent_add(tags_client):
    """Adding an existing tag twice → no duplicate in response."""
    r_list = await tags_client.get("/api/events?limit=1")
    eid = r_list.json()["items"][0]["id"]

    r1 = await tags_client.patch(
        f"/api/events/{eid}/tags",
        json={"add": ["integ-idem"], "remove": []},
    )
    r2 = await tags_client.patch(
        f"/api/events/{eid}/tags",
        json={"add": ["integ-idem"], "remove": []},
    )
    assert r1.status_code == 200 and r2.status_code == 200
    assert r2.json()["tags"].count("integ-idem") == 1


@pytest.mark.asyncio
async def test_patch_idempotent_remove_absent(tags_client):
    """Removing a tag that does not exist → 200, no error."""
    r_list = await tags_client.get("/api/events?limit=1")
    eid = r_list.json()["items"][0]["id"]

    r = await tags_client.patch(
        f"/api/events/{eid}/tags",
        json={"add": [], "remove": ["definitely-not-present-xyz-integ"]},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_patch_sorted_response(tags_client):
    """Tags in response are sorted alphabetically."""
    r_list = await tags_client.get("/api/events?limit=1")
    eid = r_list.json()["items"][0]["id"]

    r = await tags_client.patch(
        f"/api/events/{eid}/tags",
        json={"add": ["zzz-last", "aaa-first", "mmm-mid"], "remove": []},
    )
    assert r.status_code == 200
    tags = r.json()["tags"]
    assert tags == sorted(tags)


@pytest.mark.asyncio
async def test_patch_lowercased_server_side(tags_client):
    """Uppercase tags are lowercased server-side before storage."""
    r_list = await tags_client.get("/api/events?limit=1")
    eid = r_list.json()["items"][0]["id"]

    r = await tags_client.patch(
        f"/api/events/{eid}/tags",
        json={"add": ["UPPERCASETAG"], "remove": []},
    )
    assert r.status_code == 200
    assert "uppercasetag" in r.json()["tags"]
    assert "UPPERCASETAG" not in r.json()["tags"]


@pytest.mark.asyncio
async def test_patch_null_tags_event_safe(tags_client):
    """Events with tags=NULL (seed events 5,15,25) transition cleanly to a list on first add."""
    # Fetch all events; seed events 5,15,25 have NULL tags → shown as [] by GET /api/events
    r_all = await tags_client.get("/api/events?limit=200")
    assert r_all.status_code == 200
    candidates = [e for e in r_all.json()["items"] if e["tags"] == []]
    assert candidates, "seed must include events with empty/null tags"

    eid = candidates[0]["id"]
    r = await tags_client.patch(
        f"/api/events/{eid}/tags",
        json={"add": ["integ-first-tag"], "remove": []},
    )
    assert r.status_code == 200
    assert r.json()["tags"] == ["integ-first-tag"]


@pytest.mark.asyncio
async def test_patch_unknown_event_returns_404(tags_client):
    """PATCH against non-existent UUID → 404."""
    r = await tags_client.patch(
        f"/api/events/{uuid.uuid4()}/tags",
        json={"add": ["tag"], "remove": []},
    )
    assert r.status_code == 404
    assert "event not found" in r.json()["detail"]


@pytest.mark.asyncio
async def test_patch_invalid_tag_returns_422(tags_client):
    """Invalid tag format → 422 (whole request rejected, no partial success)."""
    r_list = await tags_client.get("/api/events?limit=1")
    eid = r_list.json()["items"][0]["id"]

    r = await tags_client.patch(
        f"/api/events/{eid}/tags",
        json={"add": ["BAD!TAG"], "remove": []},
    )
    assert r.status_code == 422
