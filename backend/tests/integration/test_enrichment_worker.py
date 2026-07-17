"""Integration test stubs — enrichment worker end-to-end scenarios.

Wave 0: all tests are xfail stubs. They will go GREEN when
plan 23-04 ships the enrichment worker.

Integration contracts:
  - Mocked httpx responses for each provider → ioc_enrichments rows inserted
  - Quota exhausted before actor runs → actor completes with 0 external API calls
  - 3 consecutive 429 responses → breaker key SET in Redis (TTL=3600)

Requirement coverage:
  ENRICH-02 (enrichment results persisted)
  ENRICH-03 (quota + circuit breaker)
  ENRICH-04 (resilience under quota exhaustion)
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.xfail(reason="not yet implemented —")
async def test_enrich_ioc_e2e_mocked_providers(two_project_fixture, db_session, monkeypatch):
    """Mock httpx returns valid responses for each provider; verifies ioc_enrichments rows inserted."""
    assert False, "stub — implement after 23-04 ships enrichment worker + DB migration"


@pytest.mark.xfail(reason="not yet implemented —")
async def test_enrich_ioc_quota_cap_respected(two_project_fixture, db_session, monkeypatch):
    """Quota already exhausted before actor runs → actor completes with 0 external API calls."""
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
async def test_enrich_ioc_circuit_breaker_opens(two_project_fixture, db_session, monkeypatch):
    """3 mocked 429 responses from a provider → enrich:cb:{provider} key SET in Redis."""
    assert False, "stub"
