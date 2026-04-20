"""Unit tests for GET /api/events/{id}/graph router — / graph.

Uses fake env vars + deferred imports to avoid triggering pydantic_settings
validation (DATABASE_URL, SECRET_KEY required) at collection time.

Updated in plan 09-05: router now reads dashboard_roles from request.state.user
(not X-Dashboard-Role header). Tests updated accordingly.
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# Set required env vars before any app imports happen at module load.
# This is safe: unit tests never connect to a real DB or use the actual secret.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "a" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "b" * 64)


@pytest.fixture
def app_with_router():
    """Minimal FastAPI app with graph router."""
    from app.database import get_session  # noqa: PLC0415
    from app.routers.graph import router as graph_router  # noqa: PLC0415

    app = FastAPI()
    app.include_router(graph_router, prefix="/api")
    return app


@pytest.mark.asyncio
async def test_depth_0_rejected_by_query_validator(app_with_router):
    async with AsyncClient(transport=ASGITransport(app=app_with_router), base_url="http://t") as c:
        r = await c.get(f"/api/events/{uuid.uuid4()}/graph?depth=0")
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_depth_4_rejected_by_query_validator(app_with_router):
    async with AsyncClient(transport=ASGITransport(app=app_with_router), base_url="http://t") as c:
        r = await c.get(f"/api/events/{uuid.uuid4()}/graph?depth=4")
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_depth_default_is_2(app_with_router, monkeypatch):
    """Call without depth — traverse_graph should be invoked with depth=2."""
    from app.database import get_session  # noqa: PLC0415
    from app.services.graph_traversal import DEFAULT_DEPTH  # noqa: PLC0415

    captured: dict = {}

    async def fake_traverse(session, event_id, depth, dashboard_roles=None, **kwargs):
        captured["depth"] = depth
        return None  # triggers 404 — we only need to capture arg

    monkeypatch.setattr("app.routers.graph.traverse_graph", fake_traverse)

    async def _fake_session():
        yield None

    app_with_router.dependency_overrides[get_session] = _fake_session

    async with AsyncClient(transport=ASGITransport(app=app_with_router), base_url="http://t") as c:
        r = await c.get(f"/api/events/{uuid.uuid4()}/graph")
        assert r.status_code == 404  # traverse returned None
        assert captured["depth"] == DEFAULT_DEPTH


@pytest.mark.asyncio
async def test_404_when_service_returns_none(app_with_router, monkeypatch):
    from app.database import get_session  # noqa: PLC0415

    async def fake_traverse(session, event_id, depth, dashboard_roles=None, **kwargs):
        return None

    monkeypatch.setattr("app.routers.graph.traverse_graph", fake_traverse)

    async def _fake_session():
        yield None

    app_with_router.dependency_overrides[get_session] = _fake_session

    async with AsyncClient(transport=ASGITransport(app=app_with_router), base_url="http://t") as c:
        r = await c.get(f"/api/events/{uuid.uuid4()}/graph?depth=2")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_400_on_value_error(app_with_router, monkeypatch):
    from app.database import get_session  # noqa: PLC0415

    async def fake_traverse(session, event_id, depth, dashboard_roles=None, **kwargs):
        raise ValueError("bad depth")

    monkeypatch.setattr("app.routers.graph.traverse_graph", fake_traverse)

    async def _fake_session():
        yield None

    app_with_router.dependency_overrides[get_session] = _fake_session

    async with AsyncClient(transport=ASGITransport(app=app_with_router), base_url="http://t") as c:
        # depth=2 is valid at router layer, so ValueError comes from fake fn
        r = await c.get(f"/api/events/{uuid.uuid4()}/graph?depth=2")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_successful_response_shape(app_with_router, monkeypatch):
    """Valid result from traverse_graph → 200 with correct Cytoscape shape."""
    from app.database import get_session  # noqa: PLC0415
    from app.services.graph_traversal import GraphResult  # noqa: PLC0415

    fake_result = GraphResult()
    eid = str(uuid.uuid4())
    fake_result.add_node(f"event:{eid}", "Test Event", "event")
    fake_result.add_node("technique:T1190", "T1190", "technique")
    fake_result.add_edge(f"event:{eid}", "technique:T1190", "uses")

    async def fake_traverse(session, event_id, depth, dashboard_roles=None, **kwargs):
        return fake_result

    monkeypatch.setattr("app.routers.graph.traverse_graph", fake_traverse)

    async def _fake_session():
        yield None

    app_with_router.dependency_overrides[get_session] = _fake_session

    async with AsyncClient(transport=ASGITransport(app=app_with_router), base_url="http://t") as c:
        r = await c.get(f"/api/events/{uuid.uuid4()}/graph?depth=1")
        assert r.status_code == 200
        body = r.json()
        assert "nodes" in body
        assert "edges" in body
        assert "truncated" in body
        assert body["truncated"] is False
        assert len(body["nodes"]) == 2
        assert len(body["edges"]) == 1


@pytest.mark.asyncio
async def test_depth_3_accepted(app_with_router, monkeypatch):
    """depth=3 (MAX_DEPTH) must be accepted by the router."""
    from app.database import get_session  # noqa: PLC0415
    from app.services.graph_traversal import MAX_DEPTH  # noqa: PLC0415

    async def fake_traverse(session, event_id, depth, dashboard_roles=None, **kwargs):
        return None

    monkeypatch.setattr("app.routers.graph.traverse_graph", fake_traverse)

    async def _fake_session():
        yield None

    app_with_router.dependency_overrides[get_session] = _fake_session

    async with AsyncClient(transport=ASGITransport(app=app_with_router), base_url="http://t") as c:
        r = await c.get(f"/api/events/{uuid.uuid4()}/graph?depth={MAX_DEPTH}")
        assert r.status_code == 404  # traverse None → 404, but depth was accepted


@pytest.mark.asyncio
async def test_dashboard_roles_sourced_from_request_state(app_with_router, monkeypatch):
    """dashboard_roles is sourced from request.state.user, not X-Dashboard-Role header.

    AUTH-02 / C-2 closure: even when X-Dashboard-Role=red header is sent,
    the router passes dashboard_roles from request.state.user (None when unset).
    """
    from app.database import get_session  # noqa: PLC0415

    captured: dict = {}

    async def fake_traverse(session, event_id, depth, dashboard_roles=None, **kwargs):
        captured["dashboard_roles"] = dashboard_roles
        return None

    monkeypatch.setattr("app.routers.graph.traverse_graph", fake_traverse)

    async def _fake_session():
        yield None

    app_with_router.dependency_overrides[get_session] = _fake_session

    async with AsyncClient(transport=ASGITransport(app=app_with_router), base_url="http://t") as c:
        # Send X-Dashboard-Role header — it must be IGNORED
        r = await c.get(
            f"/api/events/{uuid.uuid4()}/graph",
            headers={"X-Dashboard-Role": "red"},
        )
        assert r.status_code == 404
        # dashboard_roles must be None (no request.state.user set in this minimal test app)
        assert captured["dashboard_roles"] is None
