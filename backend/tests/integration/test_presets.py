"""Integration: /api/presets CRUD lifecycle — FIL-04."""
from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import async_session_factory
from app.main import app

pytestmark = pytest.mark.integration


async def _cleanup_preset(name: str) -> None:
    async with async_session_factory() as s:
        await s.execute(text("DELETE FROM filter_presets WHERE name = :n"), {"n": name})
        await s.commit()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_preset_full_crud_lifecycle() -> None:
    name = f"test-{uuid.uuid4().hex[:8]}"
    try:
        async with await _client() as c:
            # Create
            r = await c.post(
                "/api/presets",
                json={"name": name, "query_params": {"tlp": ["clear"]}},
            )
            assert r.status_code == 201
            body = r.json()
            assert body["name"] == name
            assert body["query_params"] == {"tlp": ["clear"]}

            # Get by name
            g = await c.get(f"/api/presets/{name}")
            assert g.status_code == 200
            assert g.json()["name"] == name

            # List includes it
            lst = await c.get("/api/presets")
            assert lst.status_code == 200
            assert any(p["name"] == name for p in lst.json())

            # Upsert (updates query_params)
            u = await c.put(
                f"/api/presets/{name}",
                json={"query_params": {"tlp": ["green"], "source_type": ["nvd"]}},
            )
            assert u.status_code == 200
            assert u.json()["query_params"] == {"tlp": ["green"], "source_type": ["nvd"]}

            # Delete
            d = await c.delete(f"/api/presets/{name}")
            assert d.status_code == 204

            # Get → 404 after delete
            g2 = await c.get(f"/api/presets/{name}")
            assert g2.status_code == 404
    finally:
        await _cleanup_preset(name)


@pytest.mark.asyncio
async def test_post_duplicate_409() -> None:
    name = f"dup-{uuid.uuid4().hex[:8]}"
    try:
        async with await _client() as c:
            r1 = await c.post("/api/presets", json={"name": name, "query_params": {}})
            assert r1.status_code == 201
            r2 = await c.post("/api/presets", json={"name": name, "query_params": {}})
            assert r2.status_code == 409
    finally:
        await _cleanup_preset(name)


@pytest.mark.asyncio
async def test_put_upsert_creates_when_absent() -> None:
    name = f"upsert-{uuid.uuid4().hex[:8]}"
    try:
        async with await _client() as c:
            r = await c.put(
                f"/api/presets/{name}",
                json={"query_params": {"source_type": ["taxii"]}},
            )
            assert r.status_code == 200
            assert r.json()["query_params"] == {"source_type": ["taxii"]}
    finally:
        await _cleanup_preset(name)


@pytest.mark.asyncio
async def test_put_upsert_bumps_updated_at() -> None:
    """: ON CONFLICT DO UPDATE must bump updated_at."""
    name = f"stamp-{uuid.uuid4().hex[:8]}"
    try:
        async with await _client() as c:
            r1 = await c.post("/api/presets", json={"name": name, "query_params": {"v": 1}})
            assert r1.status_code == 201
            created_at_1 = r1.json()["created_at"]
            updated_at_1 = r1.json()["updated_at"]

            # Small delay to get a strictly greater timestamp from now
            await asyncio.sleep(1.1)

            r2 = await c.put(f"/api/presets/{name}", json={"query_params": {"v": 2}})
            assert r2.status_code == 200
            body = r2.json()
            assert body["created_at"] == created_at_1, "created_at must be preserved on upsert"
            assert body["updated_at"] > updated_at_1, (
                f"updated_at must advance: was {updated_at_1}, now {body['updated_at']}"
            )
    finally:
        await _cleanup_preset(name)


@pytest.mark.asyncio
async def test_get_unknown_404() -> None:
    async with await _client() as c:
        r = await c.get(f"/api/presets/nonexistent-{uuid.uuid4().hex[:6]}")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_unknown_404() -> None:
    async with await _client() as c:
        r = await c.delete(f"/api/presets/nonexistent-{uuid.uuid4().hex[:6]}")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_invalid_name_in_path_422() -> None:
    """Path regex on {name} rejects uppercase, spaces, etc."""
    async with await _client() as c:
        r = await c.get("/api/presets/UPPERCASE")
        # FastAPI pattern= on Path returns 422 with validation error details
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_invalid_name_in_post_body_422() -> None:
    async with await _client() as c:
        r = await c.post("/api/presets", json={"name": "Bad Name", "query_params": {}})
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_returns_empty_array_when_no_presets() -> None:
    """GET /api/presets always returns a JSON array, even when empty."""
    async with await _client() as c:
        r = await c.get("/api/presets")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
