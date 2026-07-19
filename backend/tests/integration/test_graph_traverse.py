"""Integration smoke tests for /api/projects/{id}/graph/traverse - GRAPH-01.

Tests happy path + cross-project isolation at the HTTP layer.
Uses two_project_fixture for realistic project/user setup.
"""
from __future__ import annotations

import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.integration

TEST_SIGNING_KEY = "j" * 64


def _patch_auth(monkeypatch) -> None:
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


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _client():
    from app.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_graph_traverse_requires_project_membership(two_project_fixture, db_session, monkeypatch):
    """GRAPH-01: traverse endpoint rejects cross-project JWT with 403.

    jwt_b (Project B member) hitting Project A's traverse endpoint must get 403.
    This is the membership guard enforced by require_project_membership(Observer).
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture

    # Seed a domain IOC in project_a to have a valid seed_ioc_id
    ioc_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO iocs "
            "(id, project_id, type, value, normalized_value, status, confidence, "
            " ttl_days, source, first_seen, last_seen, created_at, updated_at) "
            "VALUES (:id, :pid, 'domain', 'cross-test.example.com', 'cross-test.example.com', "
            "        'active', 0.8, 30, 'manual', now(), now(), now(), now())"
        ),
        {"id": ioc_id, "pid": fx.project_a.id},
    )
    await db_session.commit()

    async with await _client() as c:
        r = await c.get(
            f"/api/projects/{fx.project_a.id}/graph/traverse",
            headers=_bearer(fx.jwt_b),
            params={"seed_ioc_id": str(ioc_id), "hops": 1},
        )
    assert r.status_code == 403, (
        f"LEAK: cross-project traverse returned {r.status_code}, expected 403. "
        f"Body: {r.text}"
    )


@pytest.mark.asyncio
async def test_graph_traverse_happy_path_returns_graph_response(two_project_fixture, db_session, monkeypatch):
    """GRAPH-01: traverse endpoint returns 200 with valid GraphResponse for a known domain IOC seed.

    Seeds a DomainPivot node via sync_domain_pivot(), then calls the traverse
    endpoint. Even with 0 traversal results (no SHARES_INFRA edges), the endpoint
    must return a well-formed GraphResponse.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    from app.services.age_sync import sync_domain_pivot

    ioc_id = uuid.uuid4()
    domain = f"traverse-test-{ioc_id.hex[:8]}.example.com"
    await db_session.execute(
        text(
            "INSERT INTO iocs "
            "(id, project_id, type, value, normalized_value, status, confidence, "
            " ttl_days, source, first_seen, last_seen, created_at, updated_at) "
            "VALUES (:id, :pid, 'domain', :domain, :domain, "
            "        'active', 0.8, 30, 'manual', now(), now(), now(), now())"
        ),
        {"id": ioc_id, "pid": fx.project_a.id, "domain": domain},
    )
    await db_session.commit()

    # Sync to AGE graph so the DomainPivot vertex exists
    await sync_domain_pivot(db_session, str(ioc_id), domain, str(fx.project_a.id))

    async with await _client() as c:
        r = await c.get(
            f"/api/projects/{fx.project_a.id}/graph/traverse",
            headers=_bearer(fx.jwt_a),
            params={"seed_ioc_id": str(ioc_id), "hops": 1},
        )
    assert r.status_code == 200, f"traverse endpoint returned {r.status_code}: {r.text}"

    body = r.json()
    assert "nodes" in body, f"GraphResponse missing 'nodes' key: {body}"
    assert "edges" in body, f"GraphResponse missing 'edges' key: {body}"
    assert "truncated" in body, f"GraphResponse missing 'truncated' key: {body}"
    assert isinstance(body["nodes"], list)
    assert isinstance(body["edges"], list)
    assert isinstance(body["truncated"], bool)
    # centrality fields may be None or absent for empty/single-node graph
