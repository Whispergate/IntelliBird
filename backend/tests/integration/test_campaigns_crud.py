"""Integration test stubs — campaigns CRUD + M2M event linking.

Wave 0: all tests are xfail stubs. They will go GREEN when
plan 25-05 ships the campaigns routes and service layer.

Coverage:
  ACTOR-03 — campaign CRUD: global (project_id=NULL) and project-scoped;
             M2M campaign_events link/unlink with linked_by_user_sub;
             Contributor RBAC gate for global campaigns.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.xfail(strict=False, reason="implementation pending —")
async def test_create_campaign_global():
    """POST /api/campaigns with project_id=None creates a row with project_id IS NULL.

    Global campaigns are shared across projects and visible to Lead+ callers
    regardless of project membership.
    """
    assert False, "stub — implement after campaigns routes ship"


@pytest.mark.xfail(strict=False, reason="implementation pending —")
async def test_create_campaign_scoped():
    """POST /api/campaigns with project_id=<uuid> creates a project-scoped row.

    The campaign is only visible to members of the specified project.
    """
    assert False, "stub — implement after campaigns routes ship"


@pytest.mark.xfail(strict=False, reason="implementation pending —")
async def test_link_event_to_campaign():
    """POST /api/campaigns/{id}/events/{event_id} creates a campaign_events row.

    The resulting row must have linked_by_user_sub populated from the caller's JWT.
    """
    assert False, "stub — implement after campaigns routes ship"


@pytest.mark.xfail(strict=False, reason="implementation pending —")
async def test_unlink_event_from_campaign():
    """DELETE /api/campaigns/{id}/events/{event_id} removes the campaign_events row.

    After deletion, SELECT from campaign_events WHERE campaign_id=... AND event_id=...
    must return zero rows.
    """
    assert False, "stub — implement after campaigns routes ship"


@pytest.mark.xfail(strict=False, reason="implementation pending —")
async def test_contributor_cannot_see_global_campaign():
    """Contributor role can only see project-scoped campaigns; global campaigns are absent.

    Setup: one global campaign (project_id=NULL) + one project-scoped campaign
    for Project A. A Contributor JWT for Project A hitting GET /api/campaigns
    must return only the project-scoped campaign, NOT the global one.
    """
    assert False, "stub — implement after campaigns routes ship"
