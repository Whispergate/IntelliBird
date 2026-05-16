"""Unit test stubs — Redis Lua quota script for enrichment providers.

Phase 23 Wave 0: all tests are xfail stubs. They will go GREEN when
plan 23-02 ships the quota module.

Redis key shapes:
  enrich:quota:{provider}:{project_scope}:{minute_bucket}
  enrich:daily:{provider}:{project_scope}:{YYYYMMDD}

Lua pattern mirrors app/services/llm/token_budget.py BUDGET_LUA:
  - Check current + increment against cap
  - Return {1, new_val} on allow; {0, current} on deny

Requirement coverage: ENRICH-03 (per-provider quota enforcement).

Critical stub: test_cache_hit_does_not_bump_quota — asserts the
cache-before-quota ordering contract: if get_cached_result returns a
non-None value, check_and_consume_quota must never be invoked.
"""
from __future__ import annotations

import pytest

fakeredis = pytest.importorskip("fakeredis", reason="fakeredis not installed — skip Lua quota tests")

@pytest.mark.xfail(reason="not yet implemented — Phase 23 plan 23-02")
def test_quota_allows_under_cap():
    """INCR returns 1 (allowed) when counter is 0 and cap is not reached."""
    mod = pytest.importorskip("app.services.ioc_enrichment.quota")
    assert False, "stub — implement after 23-02 ships quota module"


@pytest.mark.xfail(reason="not yet implemented — Phase 23 plan 23-02")
def test_quota_blocks_at_cap():
    """Lua script returns 0 (blocked) when counter already >= cap."""
    mod = pytest.importorskip("app.services.ioc_enrichment.quota")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented — Phase 23 plan 23-02")
def test_quota_atomic_no_race():
    """Two concurrent calls both see correct result — Lua atomicity is preserved."""
    mod = pytest.importorskip("app.services.ioc_enrichment.quota")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented — Phase 23 plan 23-02")
def test_daily_quota_blocks_when_exceeded():
    """Daily cap exceeded (enrich:daily key) → Lua returns 0 (blocked)."""
    mod = pytest.importorskip("app.services.ioc_enrichment.quota")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented — Phase 23 plan 23-02")
def test_cache_hit_does_not_bump_quota():
    """Cache-before-quota ordering contract.

    When get_cached_result returns a non-None cached payload, the Lua quota
    script (check_and_consume_quota / EVALSHA) must NEVER be invoked.

    Implementation plan:
      - Mock get_cached_result to return a non-None value
      - Mock check_and_consume_quota (or the underlying redis EVALSHA call)
      - Call the enrichment orchestrator (enrich_single_provider or similar)
      - Assert check_and_consume_quota.call_count == 0

    This is the critical ordering invariant: cache hits are free; the quota
    counter only advances on actual external API calls.
    """
    mod = pytest.importorskip("app.services.ioc_enrichment.quota")
    assert False, "stub — implement after 23-02 ships quota + cache modules"
