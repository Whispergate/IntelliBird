"""Integration: OpenAPI / Swagger surface - SYS-03."""
from __future__ import annotations

import os

# Must set required env vars before importing app modules
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "x" * 48)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest  # noqa: E402
from httpx import AsyncClient, ASGITransport  # noqa: E402

from app.main import app  # noqa: E402


pytestmark = pytest.mark.integration


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_docs_endpoint_returns_200():
    async with await _client() as c:
        r = await c.get("/docs")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_openapi_json_reachable():
    async with await _client() as c:
        r = await c.get("/openapi.json")
        assert r.status_code == 200
        spec = r.json()
        assert "paths" in spec


@pytest.mark.asyncio
async def test_openapi_lists_events_router():
    async with await _client() as c:
        spec = (await c.get("/openapi.json")).json()
        paths = spec["paths"]
        assert "/api/events" in paths
        assert "/api/events/{event_id}" in paths


@pytest.mark.asyncio
async def test_openapi_lists_tags_patch():
    async with await _client() as c:
        spec = (await c.get("/openapi.json")).json()
        paths = spec["paths"]
        assert "/api/events/{event_id}/tags" in paths
        assert "patch" in paths["/api/events/{event_id}/tags"]


@pytest.mark.asyncio
async def test_openapi_lists_presets_router():
    async with await _client() as c:
        spec = (await c.get("/openapi.json")).json()
        paths = spec["paths"]
        assert "/api/presets" in paths
        assert "/api/presets/{name}" in paths


@pytest.mark.asyncio
async def test_openapi_lists_graph_router():
    async with await _client() as c:
        spec = (await c.get("/openapi.json")).json()
        paths = spec["paths"]
        assert "/api/events/{event_id}/graph" in paths


@pytest.mark.asyncio
async def test_openapi_tags_grouped():
    """Each new router uses its designated tag (events/tags/presets/graph)."""
    async with await _client() as c:
        spec = (await c.get("/openapi.json")).json()
        paths = spec["paths"]

        # GET /api/events should have tag "events"
        assert "events" in paths["/api/events"]["get"]["tags"]
        # PATCH /api/events/{id}/tags should have tag "tags"
        assert "tags" in paths["/api/events/{event_id}/tags"]["patch"]["tags"]
        # GET /api/presets should have tag "presets"
        assert "presets" in paths["/api/presets"]["get"]["tags"]
        # GET /api/events/{id}/graph should have tag "graph"
        assert "graph" in paths["/api/events/{event_id}/graph"]["get"]["tags"]
