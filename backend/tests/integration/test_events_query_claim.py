"""/api/events with JWT derives role from claim; X-Dashboard-Role header is ignored.

AUTH-02 / C-2 closure. Activated by plan 09-05.

These tests spy on build_events_query (via the router module) to prove:
  1. dashboard_roles from JWT claim controls what is passed to the service layer.
  2. X-Dashboard-Role header has zero effect when request.state.user is set.
  3. No request.state.user (AUTH_ENABLED=false) results in dashboard_roles=None.

No testcontainer / real DB required.
"""
from __future__ import annotations

import os
import uuid
import unittest.mock as mock
from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

pytestmark = pytest.mark.integration


def _make_user(dashboard_roles: list[str]):
    from app.security.jwt import AuthUser
    return AuthUser(
        id=str(uuid.uuid4()),
        # Admin bypasses PROD-01 GAP-1 membership guard; this test targets
        # the orthogonal dashboard_roles claim path, not project scoping.
        role="Admin",
        dashboard_roles=dashboard_roles,
        jti=str(uuid.uuid4()),
        token_version=0,
    )


def _fake_session_override():
    """Async DB session that returns empty results (no real DB needed)."""
    async def override():
        from unittest.mock import AsyncMock, MagicMock
        session = AsyncMock()

        async def _execute(stmt, *a, **kw):
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            result.scalar_one.return_value = 0
            result.one_or_none.return_value = None
            result.all.return_value = []
            return result

        session.execute = _execute
        yield session

    return override


def _build_app_with_user(user_obj=None) -> FastAPI:
    """Build a minimal FastAPI app with the events router.

    Uses a custom ASGI middleware (not BaseHTTPMiddleware) to inject
    request.state.user, avoiding potential Starlette wrapper issues.
    """
    from app.database import get_session
    from app.routers.events import router as events_router

    inner = FastAPI()
    inner.include_router(events_router)
    inner.dependency_overrides[get_session] = _fake_session_override()

    # Wrap with a lightweight ASGI app that sets request.state.user
    from starlette.types import ASGIApp, Receive, Scope, Send

    class UserInjectMiddleware:
        def __init__(self, app: ASGIApp, user) -> None:
            self.app = app
            self.user = user

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "http" and self.user is not None:
                scope.setdefault("state", {})
                # Starlette's Request reads state from scope["state"]
                scope["state"]["user"] = self.user
            await self.app(scope, receive, send)

    if user_obj is not None:
        return UserInjectMiddleware(inner, user_obj)  # type: ignore[return-value]
    return inner


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_user_passes_none_dashboard_roles():
    """AUTH_ENABLED=false (no request.state.user) → dashboard_roles=None."""
    captured: dict = {}
    from app.services.events_query import build_events_query as _real_build

    def spy_build(params, dashboard_roles, **kwargs):
        # Phase 10 adds project_id/scope_predicate/bound_sources kwargs
        captured["dashboard_roles"] = dashboard_roles
        return _real_build(params, dashboard_roles, **kwargs)

    app = _build_app_with_user(user_obj=None)

    with mock.patch("app.routers.events.build_events_query", side_effect=spy_build):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/events?limit=10")

    assert r.status_code == 200
    assert captured.get("dashboard_roles") is None


@pytest.mark.asyncio
async def test_red_claim_sets_dashboard_roles_red():
    """JWT claim dashboard_roles=['red'] → router passes ['red'] to build_events_query."""
    captured: dict = {}
    from app.services.events_query import build_events_query as _real_build

    def spy_build(params, dashboard_roles, **kwargs):
        # Phase 10 adds project_id/scope_predicate/bound_sources kwargs
        captured["dashboard_roles"] = dashboard_roles
        return _real_build(params, dashboard_roles, **kwargs)

    user = _make_user(["red"])
    app = _build_app_with_user(user_obj=user)

    with mock.patch("app.routers.events.build_events_query", side_effect=spy_build):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/events?limit=10")

    assert r.status_code == 200
    assert captured.get("dashboard_roles") == ["red"]


@pytest.mark.asyncio
async def test_blue_claim_sets_dashboard_roles_blue():
    """JWT claim dashboard_roles=['blue'] → router passes ['blue'] to build_events_query."""
    captured: dict = {}
    from app.services.events_query import build_events_query as _real_build

    def spy_build(params, dashboard_roles, **kwargs):
        # Phase 10 adds project_id/scope_predicate/bound_sources kwargs
        captured["dashboard_roles"] = dashboard_roles
        return _real_build(params, dashboard_roles, **kwargs)

    user = _make_user(["blue"])
    app = _build_app_with_user(user_obj=user)

    with mock.patch("app.routers.events.build_events_query", side_effect=spy_build):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/events?limit=10")

    assert r.status_code == 200
    assert captured.get("dashboard_roles") == ["blue"]


@pytest.mark.asyncio
async def test_header_ignored_when_claim_is_blue():
    """C-2 regression: X-Dashboard-Role=red header is IGNORED when claim is blue.

    The router must pass dashboard_roles=['blue'] to the service regardless of header.
    """
    captured: dict = {}
    from app.services.events_query import build_events_query as _real_build

    def spy_build(params, dashboard_roles, **kwargs):
        # Phase 10 adds project_id/scope_predicate/bound_sources kwargs
        captured["dashboard_roles"] = dashboard_roles
        return _real_build(params, dashboard_roles, **kwargs)

    user = _make_user(["blue"])
    app = _build_app_with_user(user_obj=user)

    with mock.patch("app.routers.events.build_events_query", side_effect=spy_build):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # Send a spoofed X-Dashboard-Role: red header — must be ignored
            r = await c.get("/events?limit=10", headers={"X-Dashboard-Role": "red"})

    assert r.status_code == 200
    # dashboard_roles must reflect the CLAIM (blue), not the header (red)
    assert captured.get("dashboard_roles") == ["blue"], (
        f"Expected ['blue'] from JWT claim, got {captured.get('dashboard_roles')!r}. "
        "C-2 not closed: spoofed X-Dashboard-Role header is still influencing the service layer!"
    )


@pytest.mark.asyncio
async def test_header_ignored_when_no_user():
    """No request.state.user → dashboard_roles=None even with X-Dashboard-Role header."""
    captured: dict = {}
    from app.services.events_query import build_events_query as _real_build

    def spy_build(params, dashboard_roles, **kwargs):
        # Phase 10 adds project_id/scope_predicate/bound_sources kwargs
        captured["dashboard_roles"] = dashboard_roles
        return _real_build(params, dashboard_roles, **kwargs)

    app = _build_app_with_user(user_obj=None)

    with mock.patch("app.routers.events.build_events_query", side_effect=spy_build):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/events?limit=10", headers={"X-Dashboard-Role": "red"})

    assert r.status_code == 200
    assert captured.get("dashboard_roles") is None
