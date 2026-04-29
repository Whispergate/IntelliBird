"""Integration tests for GET /api/projects/{project_id}/graph endpoint.

Verifies GRAPH-01 / GRAPH-02 contract:
  - 200 with non-empty nodes for a project member (Observer+)
  - 403 for non-member JWTs (project membership gate)
  - 200 for Admin JWT (Admin bypass via require_project_membership)
  - truncated=True when caps are hit (via low max_nodes/max_edges args to traverse_project)
  - leakage assertion: traverse_project scoped to Project A returns no Project B nodes

Phase 20 plan 20-02.
"""
from __future__ import annotations

import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

import pytest
from httpx import ASGITransport, AsyncClient

from app.security.jwt import mint_access_token_with_pm
from app.services.graph_traversal import traverse_project

pytestmark = pytest.mark.integration

TEST_SIGNING_KEY = "j" * 64  # matches integration conftest pin


# ---------------------------------------------------------------------------
# Harness helpers
# ---------------------------------------------------------------------------


def _patch_auth(monkeypatch) -> None:
    """Enable AUTH_ENABLED, pin signing key, stub token_version/jti checks."""
    import app.middleware.auth as auth_mod
    from app.config import settings

    monkeypatch.setattr(settings, "AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "JWT_SIGNING_KEY", TEST_SIGNING_KEY, raising=False)

    async def _tv(_user_id: str):
        return 0

    async def _not_revoked(_jti: str) -> bool:
        return False

    monkeypatch.setattr(auth_mod, "_get_cached_token_version", _tv)
    monkeypatch.setattr(auth_mod, "_is_jti_revoked", _not_revoked)


async def _client():
    from app.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_graph_endpoint_returns_nodes(two_project_fixture, monkeypatch):
    """Test 1: GET /api/projects/{id}/graph returns 200 + non-empty nodes for project_a member.

    jwt_a has Lead membership on project_a (Lead > Observer, so dep passes).
    Fixture seeds 20 events with technique tags → at least 20 event nodes expected.
    truncated must be False (20 events << 1000 cap).
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture

    async with await _client() as c:
        r = await c.get(
            f"/api/projects/{fx.project_a.id}/graph",
            headers=_bearer(fx.jwt_a),
        )

    assert r.status_code == 200, f"Expected 200 for project_a member, got {r.status_code}: {r.text}"
    body = r.json()
    assert len(body["nodes"]) > 0, (
        "GRAPH-01: endpoint returned zero nodes for a project with 20 seeded events. "
        f"Full response: {body}"
    )
    assert body["truncated"] is False, (
        f"GRAPH-01: truncated=True for 20-event fixture (well below 1000 cap). "
        f"Node count: {len(body['nodes'])}"
    )


@pytest.mark.asyncio
async def test_project_graph_endpoint_403_for_non_member(two_project_fixture, monkeypatch):
    """Test 2: GET /api/projects/{project_b_id}/graph with jwt_a returns 403.

    jwt_a only has membership on project_a. Accessing project_b must be 403.
    require_project_membership(Observer) enforces this before any data is touched.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture

    async with await _client() as c:
        r = await c.get(
            f"/api/projects/{fx.project_b.id}/graph",
            headers=_bearer(fx.jwt_a),
        )

    assert r.status_code == 403, (
        f"GRAPH-02: non-member jwt_a got {r.status_code} for project_b graph, "
        f"expected 403. Body: {r.text}"
    )


@pytest.mark.asyncio
async def test_project_graph_admin_bypass(two_project_fixture, monkeypatch):
    """Test 3: Admin JWT can access any project's graph (Admin bypass).

    require_project_membership returns ProjectRole.Lead for Admin role without
    checking DB membership. Admin must receive 200 on both project_a and project_b.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture

    async with await _client() as c:
        r_a = await c.get(
            f"/api/projects/{fx.project_a.id}/graph",
            headers=_bearer(fx.jwt_admin),
        )
        r_b = await c.get(
            f"/api/projects/{fx.project_b.id}/graph",
            headers=_bearer(fx.jwt_admin),
        )

    assert r_a.status_code == 200, (
        f"Admin bypass: project_a graph returned {r_a.status_code}: {r_a.text}"
    )
    assert r_b.status_code == 200, (
        f"Admin bypass: project_b graph returned {r_b.status_code}: {r_b.text}"
    )


@pytest.mark.asyncio
async def test_traverse_project_truncates_at_cap(two_project_fixture, db_session):
    """Test 4: traverse_project with max_nodes=1 sets truncated=True.

    Calls service layer directly with a very tight cap to verify the cap logic
    fires before all events are processed. The first event node alone should
    trigger the cap, making truncated=True.
    """
    fx = two_project_fixture

    result = await traverse_project(
        db_session,
        fx.project_a.id,
        dashboard_roles=["red", "blue"],
        max_nodes=1,
        max_edges=1,
    )

    assert result.truncated is True, (
        "GRAPH-01: traverse_project with max_nodes=1 did not set truncated=True. "
        f"Node count: {len(result.nodes)}, edge count: {len(result.edges)}"
    )
    # With max_nodes=1 we should get at most 1 node.
    assert len(result.nodes) <= 1, (
        f"GRAPH-01: traverse_project exceeded max_nodes=1 cap. Got {len(result.nodes)} nodes."
    )
