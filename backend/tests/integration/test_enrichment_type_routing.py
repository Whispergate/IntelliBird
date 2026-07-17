"""Integration test stubs — IOC type-to-provider routing.

Wave 0: all tests are xfail stubs. They will go GREEN when
plan 23-04 ships the enrichment worker and routing logic.

PROVIDER_IOC_ROUTING (from CONTEXT.md):
  "vt":        {"ip", "ipv6", "domain", "url", "sha256", "sha1", "md5"}
  "abuseipdb": {"ip", "ipv6"}
  "greynoise": {"ip", "ipv6"}
  "shodan":    {"ip", "ipv6"}
  "otx":       {"domain", "sha256", "sha1", "md5"}
  "urlhaus":   {"domain", "url"}

Expected routing:
  ip      → vt, abuseipdb, greynoise, shodan  (4 providers)
  sha256  → vt, otx                           (2 providers)
  domain  → vt, otx, urlhaus                  (3 providers)
  email   → (none)                            (0 providers — silent skip)
  url     → vt, urlhaus                       (2 providers)

Requirement coverage: ENRICH-02 (correct provider dispatch by IOC type).
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.xfail(reason="not yet implemented —")
async def test_ip_routes_to_4_providers(two_project_fixture, db_session, monkeypatch):
    """IP IOC → vt, abuseipdb, greynoise, shodan all consulted (4 providers)."""
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
async def test_hash_routes_to_2_providers(two_project_fixture, db_session, monkeypatch):
    """SHA-256 IOC → vt, otx consulted (2 providers)."""
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
async def test_domain_routes_to_3_providers(two_project_fixture, db_session, monkeypatch):
    """Domain IOC → vt, otx, urlhaus consulted (3 providers)."""
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
async def test_email_routes_to_0_providers(two_project_fixture, db_session, monkeypatch):
    """Email IOC type → 0 providers consulted (silent skip, not an error)."""
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
async def test_url_routes_to_2_providers(two_project_fixture, db_session, monkeypatch):
    """URL IOC → vt, urlhaus consulted (2 providers)."""
    assert False, "stub"
