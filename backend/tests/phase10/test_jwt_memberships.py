"""test_jwt_memberships - PRJ-05 JWT pm claim + cutoff pagination (plan 10-02).

Activated by Wave 1 / plan 10-02. Exercises:
  - build_membership_claim + mint_access_token_with_pm on a user with 2 memberships
  - truncation branch when memberships > PM_CUTOFF (50)
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_pm_claim_present(db_session, users_matrix, two_projects, jwt_settings):
    """After seeding 2 project_memberships, build_membership_claim returns length-2 pm
    and mint_access_token_with_pm encodes it into the token payload."""
    from app.models.projects import ProjectMembership
    from app.security.jwt import (
        build_membership_claim,
        decode_token,
        mint_access_token_with_pm,
    )

    user = users_matrix["project_lead_user"]
    proj_a = two_projects["project_a"]
    proj_b = two_projects["project_b"]
    db_session.add(ProjectMembership(
        user_sub=str(user.id), project_id=proj_a.id,
        project_role="Lead", added_by="system",
    ))
    db_session.add(ProjectMembership(
        user_sub=str(user.id), project_id=proj_b.id,
        project_role="Contributor", added_by="system",
    ))
    await db_session.commit()

    pm, truncated = await build_membership_claim(db_session, [str(user.id)])
    assert truncated is False
    assert len(pm) == 2
    ranks = {entry[0]: entry[1] for entry in pm}
    assert ranks[str(proj_a.id)] == 3  # Lead
    assert ranks[str(proj_b.id)] == 2  # Contributor

    token, _ = mint_access_token_with_pm(
        str(user.id), user.role, user.dashboard_roles, user.token_version,
        jwt_settings, pm, truncated,
    )
    claims = decode_token(token, jwt_settings)
    assert claims["pm"] == pm
    assert claims["pm_truncated"] is False


async def test_truncation_above_cutoff(memberships_60, jwt_settings):
    """60 memberships -> pm=[] + pm_truncated=true.

    Client falls back to /api/auth/memberships (paginated endpoint in Task 3).
    """
    from app.security.jwt import decode_token

    token = memberships_60["token"]
    claims = decode_token(token, jwt_settings)
    assert claims["pm"] == []
    assert claims["pm_truncated"] is True
