"""Integration test stubs - enrichment REST API routes.

Wave 0: all tests are xfail stubs. They will go GREEN when
plan 23-05 ships the enrichment routes.

Endpoints:
  GET  /api/iocs/{id}/enrichments      - list per-provider enrichment rows
  POST /api/iocs/{id}/enrich           - trigger async enrichment actor
  POST /api/iocs/{id}/enrich?refresh=true - bypass cache, set force_refresh key in Redis

ACL:
  - GET: any authenticated project member (Analyst+ or Observer)
  - POST enrich: Lead+ only (403 for Analyst)

Requirement coverage:
  ENRICH-02 (enrichment results surfaced via API)
  ENRICH-04 (refresh-cache bypass)
  ENRICH-05 (ACL gating)
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.xfail(reason="not yet implemented -")
async def test_get_enrichments_returns_per_provider_rows(two_project_fixture, db_session, monkeypatch):
    """GET /api/iocs/{id}/enrichments returns a list of per-provider enrichment rows."""
    assert False, "stub - implement after 23-05 ships enrichment routes"


@pytest.mark.xfail(reason="not yet implemented -")
async def test_get_enrichments_respects_project_scope(two_project_fixture, monkeypatch):
    """GET /api/iocs/{id}/enrichments only returns enrichments for IOCs in the caller's project."""
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented -")
async def test_get_enrichments_analyst_can_read(two_project_fixture, monkeypatch):
    """Analyst-role project member can GET /api/iocs/{id}/enrichments (read is open to all roles)."""
    assert False, "stub - confirm Analyst is NOT blocked on GET"


@pytest.mark.xfail(reason="not yet implemented -")
async def test_post_enrich_triggers_actor(two_project_fixture, monkeypatch):
    """POST /api/iocs/{id}/enrich → 202 Accepted; enrichment actor is dispatched."""
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented -")
async def test_post_enrich_bypass_cache_with_refresh(two_project_fixture, monkeypatch):
    """POST /api/iocs/{id}/enrich?refresh=true sets enrich:force_refresh:{ioc_id} key in Redis."""
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented -")
async def test_post_enrich_lead_plus_required(two_project_fixture, monkeypatch):
    """Analyst-role member → 403 on POST /api/iocs/{id}/enrich (Lead+ only)."""
    assert False, "stub"
