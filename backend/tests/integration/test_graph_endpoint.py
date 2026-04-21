"""Integration: GET /api/events/{id}/graph against live DB + seeded events.

Uses testcontainers with intellibird-db:m1 image + alembic schema.
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


@pytest.fixture(scope="module")
def live_db_graph():
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
            "JWT_SIGNING_KEY": "j" * 64,
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


@pytest_asyncio.fixture
async def graph_client(live_db_graph):
    """Async HTTP client wired to live DB + graph + events routes."""
    asyncpg_url = live_db_graph
    engine = create_async_engine(asyncpg_url, pool_pre_ping=True, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with factory() as session:
        await seed_50_events(session)

    from app.database import get_session  # noqa: PLC0415
    from app.routers.events import router as events_router  # noqa: PLC0415
    from app.routers.graph import router as graph_router  # noqa: PLC0415

    test_app = FastAPI()
    test_app.include_router(events_router, prefix="/api")
    test_app.include_router(graph_router, prefix="/api")

    async def override_session():
        async with factory() as s:
            yield s

    test_app.dependency_overrides[get_session] = override_session

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
        yield c, factory

    await engine.dispose()


async def _event_with_t1190(factory) -> str:
    """Return event_id of the event tagged T1190."""
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT event_id FROM attack_technique_tags "
                    "WHERE technique_id = 'T1190' LIMIT 1"
                )
            )
        ).one_or_none()
        assert row is not None, "T1190 tagged event not found in seed data"
        return str(row[0])


@pytest.mark.asyncio
async def test_depth_1_returns_event_and_techniques(graph_client):
    c, factory = graph_client
    eid = await _event_with_t1190(factory)
    r = await c.get(f"/api/events/{eid}/graph?depth=1")
    assert r.status_code == 200
    body = r.json()
    ids = {n["data"]["id"] for n in body["nodes"]}
    assert any(i.startswith("event:") for i in ids)
    assert "technique:T1190" in ids
    assert body["truncated"] is False


@pytest.mark.asyncio
async def test_depth_2_includes_stix_sros(graph_client):
    """Event 0 seeded with raw_stix SRO (threat-actor--aaa → malware--bbb 'uses')."""
    c, factory = graph_client
    eid = await _event_with_t1190(factory)
    r = await c.get(f"/api/events/{eid}/graph?depth=2")
    assert r.status_code == 200
    body = r.json()
    ids = {n["data"]["id"] for n in body["nodes"]}
    assert any(i.startswith("actor:") or i.startswith("malware:") for i in ids), (
        f"depth 2 must surface SRO nodes, got {ids}"
    )


@pytest.mark.asyncio
async def test_depth_3_cross_events_same_technique(graph_client):
    """Depth 3 must return 200 (at minimum the seed + technique nodes)."""
    c, factory = graph_client
    eid = await _event_with_t1190(factory)
    r = await c.get(f"/api/events/{eid}/graph?depth=3")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_depth_4_rejected(graph_client):
    c, factory = graph_client
    eid = await _event_with_t1190(factory)
    r = await c.get(f"/api/events/{eid}/graph?depth=4")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_unknown_event_returns_404(graph_client):
    c, _factory = graph_client
    r = await c.get(f"/api/events/{uuid.uuid4()}/graph")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_default_depth_is_2(graph_client):
    """Default (no ?depth=) equals depth=2 — node set should match."""
    c, factory = graph_client
    eid = await _event_with_t1190(factory)
    r_default = await c.get(f"/api/events/{eid}/graph")
    r_2 = await c.get(f"/api/events/{eid}/graph?depth=2")
    assert r_default.status_code == 200 == r_2.status_code
    assert len(r_default.json()["nodes"]) == len(r_2.json()["nodes"])


@pytest.mark.asyncio
async def test_response_shape_cytoscape_compatible(graph_client):
    c, factory = graph_client
    eid = await _event_with_t1190(factory)
    r = await c.get(f"/api/events/{eid}/graph?depth=2")
    body = r.json()
    assert set(body.keys()) >= {"nodes", "edges", "truncated"}
    # graph_traversal may add optional 'tag_source' to technique nodes
    # (feed_asserted / stix_inferred / etc) — allow it alongside core keys.
    core = {"id", "label", "type"}
    for n in body["nodes"]:
        keys = set(n["data"].keys())
        assert core <= keys, f"node missing core keys: {keys}"
        assert keys <= core | {"tag_source"}, f"unexpected keys: {keys - core}"
    for e in body["edges"]:
        assert set(e["data"].keys()) == {"source", "target", "relation"}
