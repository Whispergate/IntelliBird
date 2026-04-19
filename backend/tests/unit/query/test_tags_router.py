"""Unit tests for PATCH /events/{id}/tags — FIL-03.

NOTE on SQLite ARRAY limitation:
 PostgreSQL ARRAY(Text) semantics (reading list, writing list) are not supported by
 SQLite in-memory. These unit tests therefore focus on:
 - 404 dispatch (unknown event UUID)
 - 422 pydantic validation (invalid/missing tag format)
 - 422 for invalid tags in remove field

 Full add/remove/idempotent/sorted/NULL-transition behaviors are covered by the
 integration tests in tests/integration/test_tags_patch.py which run against live PG.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def app_with_session():
    """Minimal FastAPI app with sqlite + tags router + events table."""
    # Import inside fixture to avoid triggering Settings validation at module load
    from app.database import get_session  # noqa: PLC0415
    from app.routers.tags import router as tags_router  # noqa: PLC0415

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        # SQLite DDL: all columns required by select(Event) ORM query.
        # ARRAY(Text) becomes TEXT; JSONB becomes TEXT; no PG-specific types.
        await conn.execute(
            text(
                "CREATE TABLE events ("
                "id TEXT PRIMARY KEY, "
                "observed_at TEXT NOT NULL DEFAULT '2025-01-01T00:00:00+00:00', "
                "stix_id TEXT, "
                "stix_type TEXT NOT NULL DEFAULT 'indicator', "
                "source_id TEXT, "
                "fetched_at TEXT NOT NULL DEFAULT '2025-01-01T00:00:00+00:00', "
                "raw_reference TEXT, "
                "title TEXT, "
                "description TEXT, "
                "confidence INTEGER, "
                "tlp_marking_id TEXT, "
                "content_hash TEXT NOT NULL DEFAULT 'hash', "
                "geo_lat REAL, "
                "geo_lon REAL, "
                "country_code TEXT, "
                "visibility TEXT NOT NULL DEFAULT 'shared', "
                "raw_stix TEXT, "
                "tags TEXT, "  # TEXT substitutes for ARRAY(Text)
                "archived INTEGER NOT NULL DEFAULT 0, "
                "created_at TEXT NOT NULL DEFAULT '2025-01-01T00:00:00+00:00'"
                ")"
            )
        )

    app = FastAPI()
    app.include_router(tags_router, prefix="/api")

    async def _override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _override

    yield app, factory

    await engine.dispose()


@pytest.mark.asyncio
async def test_patch_404_on_unknown_event(app_with_session):
    """PATCH against a UUID that does not exist in events table → 404."""
    app, _factory = app_with_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.patch(
            f"/api/events/{uuid.uuid4()}/tags",
            json={"add": ["apt28"], "remove": []},
        )
    assert r.status_code == 404
    assert "event not found" in r.json()["detail"]


@pytest.mark.asyncio
async def test_patch_422_invalid_tag_in_add(app_with_session):
    """Invalid tag (contains !) in add → 422 before any DB lookup."""
    app, _factory = app_with_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.patch(
            f"/api/events/{uuid.uuid4()}/tags",
            json={"add": ["BAD!"], "remove": []},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_422_invalid_tag_in_remove(app_with_session):
    """Invalid tag (space) in remove → 422 whole request rejected."""
    app, _factory = app_with_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.patch(
            f"/api/events/{uuid.uuid4()}/tags",
            json={"add": [], "remove": ["BAD SPACE"]},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_empty_body_noop_returns_404(app_with_session):
    """Empty add/remove is valid body — returns 404 (event not found) not 422."""
    app, _factory = app_with_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.patch(
            f"/api/events/{uuid.uuid4()}/tags",
            json={"add": [], "remove": []},
        )
    # 404 because no event in DB — NOT 422 (body is valid)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_uppercase_tag_normalised_to_422_path(app_with_session):
    """Uppercase letters are normalised to lowercase before validation — should accept."""
    app, _factory = app_with_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.patch(
            f"/api/events/{uuid.uuid4()}/tags",
            json={"add": ["UPPERCASE"], "remove": []},
        )
    # After lowercasing: 'uppercase' is valid → body accepted → 404 (no event)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_over_32_chars_tag_rejected(app_with_session):
    """Tag exceeding 32 chars rejected at schema layer → 422."""
    app, _factory = app_with_session
    long_tag = "a" * 33
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.patch(
            f"/api/events/{uuid.uuid4()}/tags",
            json={"add": [long_tag], "remove": []},
        )
    assert r.status_code == 422
