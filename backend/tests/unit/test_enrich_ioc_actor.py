"""Unit test stubs — enrich_ioc Dramatiq actor.

Wave 0: all tests are xfail stubs. They will go GREEN when
plan 23-04 ships the enrichment worker actor.

Provider routing (per CONTEXT.md):
  PROVIDER_IOC_ROUTING = {
      "vt":        {"ip", "ipv6", "domain", "url", "sha256", "sha1", "md5"},
      "abuseipdb": {"ip", "ipv6"},
      "greynoise": {"ip", "ipv6"},
      "shodan":    {"ip", "ipv6"},
      "otx":       {"domain", "sha256", "sha1", "md5"},
      "urlhaus":   {"domain", "url"},
  }

Actor contract:
  - Whitelisted IOCs → skip all enrichment (zero external calls)
  - asyncio.gather all applicable providers concurrently
  - Single provider failure does NOT abort other providers
  - Results upserted ON CONFLICT DO UPDATE (ioc_id, provider)
  - Unsupported IOC type (e.g. email) → 0 providers called

Requirement coverage: ENRICH-02 (concurrent enrichment), ENRICH-04 (resilience).
"""
from __future__ import annotations

import pytest

@pytest.mark.xfail(reason="not yet implemented —")
def test_whitelisted_ioc_skips_enrichment():
    """IOC with status='whitelisted' → zero external API calls made."""
    mod = pytest.importorskip("app.workers.ioc_enrichment")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_gather_calls_all_applicable_providers():
    """IP IOC → asyncio.gather invokes all 4 applicable providers: vt, abuseipdb, greynoise, shodan."""
    mod = pytest.importorskip("app.workers.ioc_enrichment")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_one_provider_failure_does_not_abort_others():
    """Mocked VT raises TimeoutError → other providers (abuseipdb, greynoise, shodan) still called."""
    mod = pytest.importorskip("app.workers.ioc_enrichment")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_upserts_result_to_ioc_enrichments():
    """Enrichment result is upserted into ioc_enrichments table ON CONFLICT DO UPDATE (ioc_id, provider)."""
    mod = pytest.importorskip("app.workers.ioc_enrichment")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_unsupported_ioc_type_skips_all():
    """IOC type='email' (not in any provider routing table) → 0 providers called."""
    mod = pytest.importorskip("app.workers.ioc_enrichment")
    assert False, "stub"
