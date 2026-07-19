"""Unit test stubs - enrichment result Redis cache.

Wave 0: all tests are xfail stubs. They will go GREEN when
plan 23-02 ships the cache module.

Redis key shape:
  enrich:result:{provider}:{normalized_indicator}   # 24h TTL (86400s)

Cache contract:
  - SET NX (do not overwrite existing entries)
  - TTL = 86400s (px=86_400_000 ms)
  - get_cached_result returns None on miss

Requirement coverage: ENRICH-03 (cache-before-quota; 24h result cache).
"""
from __future__ import annotations

import pytest

@pytest.mark.xfail(reason="not yet implemented -")
def test_cache_miss():
    """get_cached_result returns None for a key that has never been set."""
    pytest.importorskip("app.services.ioc_enrichment.cache")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented -")
def test_cache_hit():
    """After set_cached_result, get_cached_result returns the same payload."""
    pytest.importorskip("app.services.ioc_enrichment.cache")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented -")
def test_cache_nx_no_overwrite():
    """Second call to set_cached_result (SET NX) does NOT overwrite the existing entry."""
    pytest.importorskip("app.services.ioc_enrichment.cache")
    assert False, "stub - NX flag must be enforced"


@pytest.mark.xfail(reason="not yet implemented -")
def test_cache_ttl_is_24h():
    """Redis key TTL is 86400 seconds (px=86_400_000) after set_cached_result."""
    pytest.importorskip("app.services.ioc_enrichment.cache")
    assert False, "stub"
