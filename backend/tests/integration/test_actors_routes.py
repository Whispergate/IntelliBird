"""Integration test stubs — threat actors REST routes + RBAC.

Phase 25 Wave 0: all tests are xfail stubs. They will go GREEN when
plan 25-06 ships the /api/actors routes.

Coverage:
  ACTOR-05 — paginated actor list + profile GET endpoint
  ACTOR-06 — actor graph endpoint; Lead+ RBAC for create/edit;
             Contributor 403 on write operations.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.xfail(strict=False, reason="implementation pending — Phase 25 plan 25-06")
async def test_list_actors_returns_paginated():
    """GET /api/actors returns a cursor-paginated response.

    Response shape: { items: [...], next_cursor: <str|null> }
    Must return at least one actor after bootstrap.
    """
    assert False, "stub — implement after actors routes ship"


@pytest.mark.xfail(strict=False, reason="implementation pending — Phase 25 plan 25-06")
async def test_get_actor_profile():
    """GET /api/actors/{id} returns full actor profile with expected fields.

    Response must include: aliases (list), country, motivation, sophistication.
    """
    assert False, "stub — implement after actors routes ship"


@pytest.mark.xfail(strict=False, reason="implementation pending — Phase 25 plan 25-06")
async def test_get_actor_graph():
    """GET /api/actors/{id}/graph returns graph nodes and edges.

    Response shape: { nodes: [...], edges: [...] }
    Nodes represent events linked to the actor via actor_event_links.
    """
    assert False, "stub — implement after actors routes ship"


@pytest.mark.xfail(strict=False, reason="implementation pending — Phase 25 plan 25-06")
async def test_actor_edit_rbac_lead_plus():
    """Lead+ PATCH /api/actors/{id} returns 200.

    A caller with Lead or higher role must be able to edit actor profile fields
    (e.g. profile_md, motivation, sophistication).
    """
    assert False, "stub — implement after actors routes ship"


@pytest.mark.xfail(strict=False, reason="implementation pending — Phase 25 plan 25-06")
async def test_actor_edit_rbac_contributor_403():
    """Contributor PATCH /api/actors/{id} returns 403.

    Write access to actor records is gated at Lead+ — Contributor role must
    receive a 403 Forbidden response.
    """
    assert False, "stub — implement after actors routes ship"


@pytest.mark.xfail(strict=False, reason="implementation pending — Phase 25 plan 25-06")
async def test_create_actor_lead_plus():
    """Lead+ POST /api/actors returns 201 Created.

    A caller with Lead or higher role must be able to create a new threat actor
    record. Response must include the new actor's id.
    """
    assert False, "stub — implement after actors routes ship"
