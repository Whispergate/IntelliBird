"""Integration test stubs — enrichment_providers CRUD API.

Phase 23 Wave 0: all tests are xfail stubs. They will go GREEN when
plan 23-03 ships the providers CRUD routes and migration.

Table: enrichment_providers
  - project_id UUID | NULL (NULL = global fallback)
  - provider VARCHAR (vt|abuseipdb|greynoise|otx|shodan|urlhaus)
  - api_key TEXT (encrypted at rest in later plan)
  - enabled BOOLEAN DEFAULT FALSE
  - breaker_open_until TIMESTAMPTZ | NULL
  UNIQUE (project_id, provider) DEFERRABLE INITIALLY DEFERRED

ACL: Lead+ required for PUT (upsert); any authenticated member can GET.

Requirement coverage: ENRICH-01 (per-project provider key management).
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.xfail(reason="not yet implemented — Phase 23 plan 23-03")
async def test_upsert_per_project_provider(two_project_fixture, db_session, monkeypatch):
    """PUT /api/projects/{id}/enrichment-providers/{provider} creates a per-project row."""
    assert False, "stub — implement after 23-03 ships providers CRUD routes"


@pytest.mark.xfail(reason="not yet implemented — Phase 23 plan 23-03")
async def test_global_fallback_row_creation(db_session, monkeypatch):
    """PUT with project_id=None (global scope) creates a global fallback row."""
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented — Phase 23 plan 23-03")
async def test_disabled_by_default(two_project_fixture, db_session, monkeypatch):
    """Freshly created enrichment_providers row has enabled=False by default."""
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented — Phase 23 plan 23-03")
async def test_list_providers_returns_6(two_project_fixture, db_session, monkeypatch):
    """GET /api/projects/{id}/enrichment-providers lists all 6 provider slots for a project."""
    assert False, "stub — 6 providers: vt, abuseipdb, greynoise, otx, shodan, urlhaus"


@pytest.mark.xfail(reason="not yet implemented — Phase 23 plan 23-03")
async def test_acl_lead_plus_required(two_project_fixture, monkeypatch):
    """Analyst role → 403 on PUT /api/projects/{id}/enrichment-providers/{provider}."""
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented — Phase 23 plan 23-03")
async def test_project_b_providers_not_visible_to_project_a(two_project_fixture, monkeypatch):
    """Cross-project ACL: Project A caller cannot list/modify Project B providers."""
    assert False, "stub"
