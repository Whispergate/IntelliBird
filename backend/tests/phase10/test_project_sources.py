"""test_project_sources - PRJ-05 project_sources binding (plan 10-04).

Covers:
  * test_binding_restricts: PUT replaces atomically; empty PUT removes all.
  * test_unknown_source_id_422: FK violation translated to 422.
  * test_observer_cannot_bind: Observer role receives 403 on PUT.

Uses admin_token (Admin bypass of require_project_membership) for the first two
tests to sidestep the "token minted before project exists has no pm claim"
chicken-and-egg (pattern established in plan 10-03 `test_last_lead_protection`).
The Observer 403 test re-mints the observer token with a real pm claim so the
authority gate is exercised end-to-end.
"""
from __future__ import annotations

import uuid as _uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def client(db_engine, monkeypatch):
    """AsyncClient wired to the app with get_session overridden to test DB engine."""
    from app.config import settings
    from app.database import get_session
    from app.main import app
    import app.middleware.auth as auth_mod

    monkeypatch.setattr(settings, "AUTH_ENABLED", True, raising=False)

    async def _fake_tv(user_id: str):
        return 0

    async def _fake_revoked(jti: str) -> bool:
        return False

    monkeypatch.setattr(auth_mod, "_get_cached_token_version", _fake_tv)
    monkeypatch.setattr(auth_mod, "_is_jti_revoked", _fake_revoked)

    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override_session():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _override_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


async def _seed_sources(db_session) -> tuple[_uuid.UUID, _uuid.UUID]:
    """Insert two sources and return their ids."""
    from app.models.sources import Source

    s1_id = _uuid.uuid4()
    s2_id = _uuid.uuid4()
    db_session.add_all(
        [
            Source(
                id=s1_id, name="src1", feed_type="rss", url="http://x",
                poll_interval_sec=3600, hot_retention_days=7, enabled=True,
            ),
            Source(
                id=s2_id, name="src2", feed_type="nvd", url="http://y",
                poll_interval_sec=3600, hot_retention_days=7, enabled=True,
            ),
        ]
    )
    await db_session.commit()
    return s1_id, s2_id


async def test_binding_restricts(client, db_session, users_matrix) -> None:
    """PUT with one source restricts; empty PUT removes all (all-sources fallback)."""
    admin_token = users_matrix["tokens"]["admin"]
    s1_id, s2_id = await _seed_sources(db_session)

    proj = (
        await client.post(
            "/api/projects",
            json={"name": "Src Binding", "engagement_type": "internal"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()
    pid = proj["id"]

    # Bind source 1 only
    r_put = await client.put(
        f"/api/projects/{pid}/sources",
        json={"source_ids": [str(s1_id)]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_put.status_code == 200, r_put.text
    assert len(r_put.json()) == 1
    assert r_put.json()[0]["source_id"] == str(s1_id)
    assert r_put.json()[0]["source_name"] == "src1"
    assert r_put.json()[0]["feed_type"] == "rss"

    # GET confirms single binding
    r_get = await client.get(
        f"/api/projects/{pid}/sources",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_get.status_code == 200
    assert len(r_get.json()) == 1
    assert r_get.json()[0]["source_id"] == str(s1_id)

    # Atomic replace: PUT with [s2] removes s1 + adds s2 in one transaction
    r_swap = await client.put(
        f"/api/projects/{pid}/sources",
        json={"source_ids": [str(s2_id)]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_swap.status_code == 200
    assert len(r_swap.json()) == 1
    assert r_swap.json()[0]["source_id"] == str(s2_id)

    # Empty PUT removes all
    r_empty = await client.put(
        f"/api/projects/{pid}/sources",
        json={"source_ids": []},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_empty.status_code == 200
    assert r_empty.json() == []


async def test_unknown_source_id_422(client, users_matrix) -> None:
    """FK violation on unknown source_id is translated to 422 unknown_source_id."""
    admin_token = users_matrix["tokens"]["admin"]
    proj = (
        await client.post(
            "/api/projects",
            json={"name": "Bad Src", "engagement_type": "internal"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()
    pid = proj["id"]

    bogus = str(_uuid.uuid4())
    r = await client.put(
        f"/api/projects/{pid}/sources",
        json={"source_ids": [bogus]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "unknown_source_id"


async def test_observer_cannot_bind(
    client, db_session, users_matrix, jwt_settings
) -> None:
    """Observer role on a project receives 403 on PUT /sources (Contributor+ required)."""
    from app.security.jwt import (
        build_membership_claim,
        mint_access_token_with_pm,
    )

    # Use admin to create a project, then add observer as Observer
    observer = users_matrix["project_observer_user"]
    admin_token = users_matrix["tokens"]["admin"]

    proj_resp = (
        await client.post(
            "/api/projects",
            json={"name": "Obs Bind Proj", "engagement_type": "internal"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()
    pid = proj_resp["id"]

    # Add observer as Observer via the admin endpoint
    r_add = await client.post(
        f"/api/projects/{pid}/memberships",
        json={"user_sub": str(observer.id), "project_role": "Observer"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_add.status_code == 201, r_add.text

    # Mint observer token with real pm claim so require_project_membership
    # resolves via the claim-cache hit path (not Admin bypass).
    pm, truncated = await build_membership_claim(db_session, [str(observer.id)])
    obs_token, _ = mint_access_token_with_pm(
        str(observer.id),
        observer.role,
        observer.dashboard_roles,
        observer.token_version,
        jwt_settings,
        pm,
        truncated,
    )

    # Observer is blocked from PUT (Contributor+ required)
    r = await client.put(
        f"/api/projects/{pid}/sources",
        json={"source_ids": []},
        headers={"Authorization": f"Bearer {obs_token}"},
    )
    assert r.status_code == 403, r.text

    # But Observer CAN GET (Observer gate is the read threshold)
    r_get = await client.get(
        f"/api/projects/{pid}/sources",
        headers={"Authorization": f"Bearer {obs_token}"},
    )
    assert r_get.status_code == 200
