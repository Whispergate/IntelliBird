"""/api/events/{id}/graph with JWT derives role from claim; X-Dashboard-Role header is ignored.

AUTH-02 / C-2 closure. Activated by plan 09-05.

These tests use a minimal FastAPI app with monkeypatched traverse_graph to prove:
  1. dashboard_roles from JWT claim is passed to traverse_graph.
  2. X-Dashboard-Role header has zero effect when request.state.user is set.
  3. No request.state.user (AUTH_ENABLED=false) passes dashboard_roles=None.

No testcontainer / real DB required.
"""
from __future__ import annotations

import os
import uuid
import unittest.mock as mock

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

pytestmark = pytest.mark.integration


def _make_user(dashboard_roles: list[str]):
    from app.security.jwt import AuthUser
    return AuthUser(
        id=str(uuid.uuid4()),
        # Admin bypasses PROD-01 GAP-2 membership guard on graph router;
        # this test targets dashboard_roles claim plumbing, not scoping.
        role="Admin",
        dashboard_roles=dashboard_roles,
        jti=str(uuid.uuid4()),
        token_version=0,
    )


def _build_graph_app(user_obj=None):
    """Minimal FastAPI app with graph router and injected request.state.user."""
    from fastapi import FastAPI
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response
    from app.database import get_session
    from app.routers.graph import router as graph_router

    app = FastAPI()

    class InjectUserMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next) -> Response:
            if user_obj is not None:
                request.state.user = user_obj
            return await call_next(request)

    app.add_middleware(InjectUserMiddleware)
    app.include_router(graph_router, prefix="/api")

    async def fake_session():
        yield None

    app.dependency_overrides[get_session] = fake_session
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_user_passes_none_dashboard_roles():
    """AUTH_ENABLED=false (no request.state.user) → dashboard_roles=None passed to traverse_graph."""
    from httpx import ASGITransport, AsyncClient

    captured: dict = {}

    async def fake_traverse(session, event_id, depth, dashboard_roles=None, **kwargs):
        # adds project_id kwarg
        captured["dashboard_roles"] = dashboard_roles
        return None

    app = _build_graph_app(user_obj=None)
    eid = uuid.uuid4()

    with mock.patch("app.routers.graph.traverse_graph", side_effect=fake_traverse):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(f"/api/events/{eid}/graph")

    assert r.status_code == 404  # traverse returned None → 404
    assert captured.get("dashboard_roles") is None


@pytest.mark.asyncio
async def test_red_claim_passes_red_dashboard_roles():
    """JWT claim dashboard_roles=['red'] → traverse_graph receives ['red']."""
    from httpx import ASGITransport, AsyncClient

    captured: dict = {}

    async def fake_traverse(session, event_id, depth, dashboard_roles=None, **kwargs):
        # adds project_id kwarg
        captured["dashboard_roles"] = dashboard_roles
        return None

    user = _make_user(["red"])
    app = _build_graph_app(user_obj=user)
    eid = uuid.uuid4()

    with mock.patch("app.routers.graph.traverse_graph", side_effect=fake_traverse):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(f"/api/events/{eid}/graph")

    assert r.status_code == 404
    assert captured.get("dashboard_roles") == ["red"]


@pytest.mark.asyncio
async def test_blue_claim_passes_blue_dashboard_roles():
    """JWT claim dashboard_roles=['blue'] → traverse_graph receives ['blue']."""
    from httpx import ASGITransport, AsyncClient

    captured: dict = {}

    async def fake_traverse(session, event_id, depth, dashboard_roles=None, **kwargs):
        # adds project_id kwarg
        captured["dashboard_roles"] = dashboard_roles
        return None

    user = _make_user(["blue"])
    app = _build_graph_app(user_obj=user)
    eid = uuid.uuid4()

    with mock.patch("app.routers.graph.traverse_graph", side_effect=fake_traverse):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(f"/api/events/{eid}/graph")

    assert r.status_code == 404
    assert captured.get("dashboard_roles") == ["blue"]


@pytest.mark.asyncio
async def test_header_ignored_when_claim_is_blue():
    """C-2 regression: X-Dashboard-Role=red header is IGNORED when claim is blue.

    traverse_graph must receive ['blue'] from the JWT claim, not ['red'] from header.
    """
    from httpx import ASGITransport, AsyncClient

    captured: dict = {}

    async def fake_traverse(session, event_id, depth, dashboard_roles=None, **kwargs):
        # adds project_id kwarg
        captured["dashboard_roles"] = dashboard_roles
        return None

    user = _make_user(["blue"])
    app = _build_graph_app(user_obj=user)
    eid = uuid.uuid4()

    with mock.patch("app.routers.graph.traverse_graph", side_effect=fake_traverse):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # Send spoofed X-Dashboard-Role: red - must be ignored
            r = await c.get(
                f"/api/events/{eid}/graph",
                headers={"X-Dashboard-Role": "red"},
            )

    assert r.status_code == 404
    assert captured.get("dashboard_roles") == ["blue"], (
        f"Expected ['blue'] from claim, got {captured.get('dashboard_roles')!r} - "
        "C-2 not closed: header is still influencing graph traversal role!"
    )


@pytest.mark.asyncio
async def test_both_roles_claim_passes_both():
    """JWT claim dashboard_roles=['red','blue'] → traverse_graph receives both roles."""
    from httpx import ASGITransport, AsyncClient

    captured: dict = {}

    async def fake_traverse(session, event_id, depth, dashboard_roles=None, **kwargs):
        # adds project_id kwarg
        captured["dashboard_roles"] = dashboard_roles
        return None

    user = _make_user(["red", "blue"])
    app = _build_graph_app(user_obj=user)
    eid = uuid.uuid4()

    with mock.patch("app.routers.graph.traverse_graph", side_effect=fake_traverse):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(f"/api/events/{eid}/graph")

    assert r.status_code == 404
    roles = captured.get("dashboard_roles") or []
    assert set(roles) == {"red", "blue"}


@pytest.mark.asyncio
async def test_header_ignored_when_no_user():
    """When no request.state.user, dashboard_roles=None even if X-Dashboard-Role header sent."""
    from httpx import ASGITransport, AsyncClient

    captured: dict = {}

    async def fake_traverse(session, event_id, depth, dashboard_roles=None, **kwargs):
        # adds project_id kwarg
        captured["dashboard_roles"] = dashboard_roles
        return None

    app = _build_graph_app(user_obj=None)
    eid = uuid.uuid4()

    with mock.patch("app.routers.graph.traverse_graph", side_effect=fake_traverse):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(
                f"/api/events/{eid}/graph",
                headers={"X-Dashboard-Role": "red"},
            )

    assert r.status_code == 404
    assert captured.get("dashboard_roles") is None
