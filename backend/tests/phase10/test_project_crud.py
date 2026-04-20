"""test_project_crud — PRJ-01 (plan 10-03 implementation).

Exercises /api/projects CRUD: creator auto-join as Lead, Viewer 403 on create,
soft archive + include_archived filter, legacy sentinel immutability.

Uses AsyncClient + ASGITransport wired to the full app; overrides get_session
so router writes land in the same testcontainer Postgres as the db_session
fixture. AuthMiddleware helpers (_get_cached_token_version + _is_jti_revoked)
are monkeypatched to bypass DB/Redis lookups — tokens come from users_matrix
fixture which minted them with the test JWT_SIGNING_KEY.
"""
from __future__ import annotations

import uuid as _uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.projects import LEGACY_PROJECT_ID, ProjectMembership

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def client(db_engine, monkeypatch):
    """AsyncClient wired to app with get_session overridden to the test DB engine.

    - Sets AUTH_ENABLED=True so AuthMiddleware validates bearer tokens end-to-end.
    - Monkeypatches _get_cached_token_version to return 0 (matches minted tokens).
    - Monkeypatches _is_jti_revoked to return False (no Redis dependency).
    """
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


# ---------------------------------------------------------------------------
# POST /api/projects — create + auto-Lead
# ---------------------------------------------------------------------------


async def test_create_auto_lead(client: AsyncClient, db_session, users_matrix):
    """Analyst POSTs a project; creator is atomically inserted as Lead."""
    analyst_token = users_matrix["tokens"]["analyst"]
    r = await client.post(
        "/api/projects",
        json={
            "name": "Test Red Team 1",
            "engagement_type": "red_team",
            "description": "auto-lead test",
        },
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    proj_id = _uuid.UUID(data["id"])
    assert data["member_count"] == 1
    assert data["creator_is_current_user"] is True

    row = (
        await db_session.execute(
            select(ProjectMembership).where(ProjectMembership.project_id == proj_id)
        )
    ).scalar_one()
    assert row.project_role == "Lead"
    assert row.user_sub == str(users_matrix["global_analyst"].id)


async def test_viewer_403(client: AsyncClient, users_matrix):
    """Viewer POST /api/projects is forbidden — require_analyst_or_above gate."""
    viewer_token = users_matrix["tokens"]["observer"]
    r = await client.post(
        "/api/projects",
        json={"name": "Should fail", "engagement_type": "internal"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /{id}/archive — soft delete + GET include_archived filter
# ---------------------------------------------------------------------------


async def test_archive_soft(client: AsyncClient, users_matrix):
    """Archive flips the flag (row preserved); GET default hides, include_archived shows."""
    admin_token = users_matrix["tokens"]["admin"]
    created = (
        await client.post(
            "/api/projects",
            json={"name": "Archive Test", "engagement_type": "internal"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()
    pid = created["id"]

    r_arch = await client.post(
        f"/api/projects/{pid}/archive",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_arch.status_code == 200, r_arch.text
    assert r_arch.json()["archived"] is True

    # Default list hides archived projects
    r_list = await client.get(
        "/api/projects", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r_list.status_code == 200, r_list.text
    pids_in_list = {row["id"] for row in r_list.json()}
    assert pid not in pids_in_list

    # include_archived=true reveals them
    r_list2 = await client.get(
        "/api/projects?include_archived=true",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_list2.status_code == 200
    pids_in_list2 = {row["id"] for row in r_list2.json()}
    assert pid in pids_in_list2


# ---------------------------------------------------------------------------
# Legacy sentinel immutability
# ---------------------------------------------------------------------------


async def test_legacy_immutable(client: AsyncClient, users_matrix):
    """PATCH against the legacy sentinel project returns 403 legacy_project_immutable.

    Global Admin bypasses the membership gate, so the legacy guard itself must
    reject the write — otherwise the sentinel could be renamed/unarchived.
    """
    admin_token = users_matrix["tokens"]["admin"]
    r = await client.patch(
        f"/api/projects/{LEGACY_PROJECT_ID}",
        json={"name": "hack"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "legacy_project_immutable"


# ---------------------------------------------------------------------------
# Bonus: global Admin bypass on GET /api/projects
# ---------------------------------------------------------------------------


async def test_admin_bypass_sees_all_projects(client: AsyncClient, users_matrix):
    """Global Admin sees every non-archived project even without membership."""
    analyst_token = users_matrix["tokens"]["analyst"]
    admin_token = users_matrix["tokens"]["admin"]
    # Analyst creates a project — Admin is NOT a member.
    created = (
        await client.post(
            "/api/projects",
            json={"name": "Analyst Only", "engagement_type": "internal"},
            headers={"Authorization": f"Bearer {analyst_token}"},
        )
    ).json()
    pid = created["id"]
    r_admin = await client.get(
        "/api/projects", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r_admin.status_code == 200
    admin_pids = {row["id"] for row in r_admin.json()}
    assert pid in admin_pids
