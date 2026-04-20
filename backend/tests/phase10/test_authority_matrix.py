"""test_authority_matrix — PRJ-05 authority gates (plan 10-02 dep layer + 10-03 last-Lead).

Plan 10-02 seeded tests:
  test_admin_bypass           -> Global Admin resolves to Lead with no DB query
  test_observer_read_only     -> Observer passes Observer gate, fails Contributor gate
  test_contributor_scope_only -> Contributor passes Contributor gate, fails Lead gate

Plan 10-03 appended:
  test_last_lead_protection              -> Sole Lead cannot demote or remove self (409)
  test_last_lead_protection_with_second_lead -> With a second Lead, self-demote works

The DB-fallback branch (pm_truncated=true) is covered by Plan 10-03+ router tests;
this file hits the claim-cache path with a synthetic AuthUser instance for the
plan-10-02 suite and real HTTP round-trips for the plan-10-03 additions.
"""
from __future__ import annotations

import uuid as _uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


async def test_admin_bypass(db_session, users_matrix):
    """Global Admin resolves to Lead regardless of membership table contents."""
    from app.models.projects import ProjectRole
    from app.security.jwt import AuthUser
    from app.security.project_membership import require_project_membership

    dep = require_project_membership(ProjectRole.Lead)
    admin = users_matrix["global_admin"]
    admin_user = AuthUser(
        id=str(admin.id), role="Admin",
        dashboard_roles=["red", "blue"], jti="j",
        token_version=0, project_memberships={}, pm_truncated=False,
    )
    role = await dep(project_id=_uuid.uuid4(), user=admin_user, db=db_session)
    assert role == ProjectRole.Lead


async def test_observer_read_only(db_session, users_matrix, two_projects):
    """Observer on a project passes Observer gate but fails Contributor gate."""
    from app.models.projects import ProjectMembership, ProjectRole
    from app.security.jwt import AuthUser, PROJECT_ROLE_RANK
    from app.security.project_membership import require_project_membership

    observer = users_matrix["project_observer_user"]
    proj = two_projects["project_a"]
    db_session.add(ProjectMembership(
        user_sub=str(observer.id), project_id=proj.id,
        project_role="Observer", added_by="system",
    ))
    await db_session.commit()

    observer_user = AuthUser(
        id=str(observer.id), role="Viewer",
        dashboard_roles=["blue"], jti="j", token_version=0,
        project_memberships={str(proj.id): PROJECT_ROLE_RANK["Observer"]},
        pm_truncated=False,
    )
    # Observer gate passes
    ok = await require_project_membership(ProjectRole.Observer)(
        project_id=proj.id, user=observer_user, db=db_session,
    )
    assert ok == ProjectRole.Observer
    # Contributor gate raises 403
    with pytest.raises(HTTPException) as exc:
        await require_project_membership(ProjectRole.Contributor)(
            project_id=proj.id, user=observer_user, db=db_session,
        )
    assert exc.value.status_code == 403


async def test_contributor_scope_only(db_session, users_matrix, two_projects):
    """Contributor passes Contributor gate, fails Lead gate."""
    from app.models.projects import ProjectMembership, ProjectRole
    from app.security.jwt import AuthUser, PROJECT_ROLE_RANK
    from app.security.project_membership import require_project_membership

    contrib = users_matrix["project_contributor_user"]
    proj = two_projects["project_a"]
    db_session.add(ProjectMembership(
        user_sub=str(contrib.id), project_id=proj.id,
        project_role="Contributor", added_by="system",
    ))
    await db_session.commit()

    contrib_user = AuthUser(
        id=str(contrib.id), role="Analyst",
        dashboard_roles=["blue"], jti="j", token_version=0,
        project_memberships={str(proj.id): PROJECT_ROLE_RANK["Contributor"]},
        pm_truncated=False,
    )
    ok = await require_project_membership(ProjectRole.Contributor)(
        project_id=proj.id, user=contrib_user, db=db_session,
    )
    assert ok == ProjectRole.Contributor
    with pytest.raises(HTTPException) as exc:
        await require_project_membership(ProjectRole.Lead)(
            project_id=proj.id, user=contrib_user, db=db_session,
        )
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Plan 10-03 additions — last-Lead protection (real HTTP round-trips)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(db_engine, monkeypatch):
    """AsyncClient wired to app with get_session overridden to the test DB engine."""
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


def _mint_token_with_pm(user, pm, jwt_key: str, *, truncated: bool = False) -> str:
    """Mint an access token including the given pm claim.

    Used after creating projects so the Analyst's token reflects the fresh
    Lead membership. In production, clients refresh after mutation events;
    in tests we simulate with a fresh mint.
    """
    from app.security.jwt import mint_access_token_with_pm
    tok, _ = mint_access_token_with_pm(
        str(user.id), user.role, user.dashboard_roles, user.token_version,
        jwt_key, pm, truncated,
    )
    return tok


async def test_last_lead_protection(client: AsyncClient, users_matrix, jwt_settings):
    """Sole Lead on a project cannot demote or remove themselves (409).

    Uses Admin to drive the membership ops — Admin bypasses the membership gate
    so we do not need to re-mint the Analyst token after project creation. The
    last-Lead check itself runs inside the router (not the auth dep), so Admin
    still triggers the 409.
    """
    from app.security.jwt import PROJECT_ROLE_RANK
    analyst_token = users_matrix["tokens"]["analyst"]
    admin_token = users_matrix["tokens"]["admin"]

    # Analyst creates project — creator auto-joins as sole Lead.
    r_create = await client.post(
        "/api/projects",
        json={"name": "Solo Lead", "engagement_type": "internal"},
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert r_create.status_code == 201, r_create.text
    proj_id = r_create.json()["id"]

    # Admin lists memberships (bypasses gate) to locate the sole Lead row.
    r_memberships = await client.get(
        f"/api/projects/{proj_id}/memberships",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_memberships.status_code == 200, r_memberships.text
    memberships = r_memberships.json()
    assert len(memberships) == 1
    assert memberships[0]["project_role"] == "Lead"
    mid = memberships[0]["id"]

    # Admin attempts to demote the sole Lead — 409 cannot_remove_last_lead.
    # The last-Lead check is a router invariant — not bypassed by Admin.
    r_patch = await client.patch(
        f"/api/projects/{proj_id}/memberships/{mid}",
        json={"project_role": "Contributor"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_patch.status_code == 409, r_patch.text
    assert r_patch.json()["detail"] == "cannot_remove_last_lead"

    # Admin attempts DELETE of the sole Lead — also 409.
    r_del = await client.delete(
        f"/api/projects/{proj_id}/memberships/{mid}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_del.status_code == 409
    assert r_del.json()["detail"] == "cannot_remove_last_lead"


async def test_last_lead_protection_with_second_lead(client: AsyncClient, users_matrix):
    """With a second Lead in place, the first Lead can be demoted."""
    analyst_token = users_matrix["tokens"]["analyst"]
    admin_token = users_matrix["tokens"]["admin"]

    r_create = await client.post(
        "/api/projects",
        json={"name": "Two Leads", "engagement_type": "internal"},
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert r_create.status_code == 201
    proj_id = r_create.json()["id"]

    # Admin adds a second Lead
    second_user = users_matrix["project_lead_user"]
    r_add = await client.post(
        f"/api/projects/{proj_id}/memberships",
        json={"user_sub": str(second_user.id), "project_role": "Lead"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_add.status_code == 201, r_add.text

    # Admin lists to find the first (creator) Lead's membership
    r_memberships = await client.get(
        f"/api/projects/{proj_id}/memberships",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_memberships.status_code == 200
    own = [
        m for m in r_memberships.json()
        if m["user_sub"] == str(users_matrix["global_analyst"].id)
    ][0]

    # Now demoting the first Lead works (a second Lead remains).
    r_demote = await client.patch(
        f"/api/projects/{proj_id}/memberships/{own['id']}",
        json={"project_role": "Contributor"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_demote.status_code == 200, r_demote.text
    assert r_demote.json()["project_role"] == "Contributor"


async def test_lead_can_manage_own_project_after_token_refresh(
    client: AsyncClient, users_matrix, jwt_settings
):
    """After the creator refreshes their token, they can manage memberships as Lead.

    Illustrates the real-world flow: Analyst creates project, then refreshes their
    access token so the new Lead membership lands in the pm claim.
    """
    from app.security.jwt import PROJECT_ROLE_RANK
    analyst = users_matrix["global_analyst"]
    analyst_token = users_matrix["tokens"]["analyst"]

    r_create = await client.post(
        "/api/projects",
        json={"name": "Lead Manages", "engagement_type": "internal"},
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert r_create.status_code == 201
    proj_id = r_create.json()["id"]

    # Re-mint Analyst's token with the new Lead membership (simulates refresh)
    refreshed_token = _mint_token_with_pm(
        analyst,
        [[proj_id, PROJECT_ROLE_RANK["Lead"]]],
        jwt_settings,
    )

    # Now Analyst can list memberships on their own project
    r_memberships = await client.get(
        f"/api/projects/{proj_id}/memberships",
        headers={"Authorization": f"Bearer {refreshed_token}"},
    )
    assert r_memberships.status_code == 200, r_memberships.text
    memberships = r_memberships.json()
    assert len(memberships) == 1
    assert memberships[0]["project_role"] == "Lead"


async def test_legacy_memberships_write_forbidden(client: AsyncClient, users_matrix):
    """POST /api/projects/{LEGACY}/memberships returns 403 legacy_project_immutable."""
    from app.models.projects import LEGACY_PROJECT_ID
    admin_token = users_matrix["tokens"]["admin"]
    # Need an existing user_sub to add — use the admin's own id
    r = await client.post(
        f"/api/projects/{LEGACY_PROJECT_ID}/memberships",
        json={
            "user_sub": str(users_matrix["global_admin"].id),
            "project_role": "Observer",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "legacy_project_immutable"
