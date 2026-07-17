"""Unit test stubs — enrichment provider circuit breaker state machine.

Wave 0: all tests are xfail stubs. They will go GREEN when
plan 23-02 ships the circuit breaker module.

Redis key shapes:
  enrich:cb:{provider}:{project_scope}         # breaker open key, TTL=3600
  enrich:cb:fails:{provider}:{project_scope}   # consecutive failure counter, TTL=300

State machine:
  - 3 consecutive failures → SET enrich:cb key (breaker OPEN)
  - is_breaker_open → True while key exists
  - record_success → DEL enrich:cb:fails key (reset counter)
  - Key expiry → is_breaker_open → False (auto-reset after TTL)

Requirement coverage: ENRICH-03 (circuit breaker preventing cascade failures).
"""
from __future__ import annotations

import pytest

@pytest.mark.xfail(reason="not yet implemented —")
def test_breaker_open_after_3_failures():
    """3 calls to record_quota_failure for same provider → breaker key SET → is_breaker_open True."""
    mod = pytest.importorskip("app.services.ioc_enrichment.circuit_breaker")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_breaker_not_open_after_2_failures():
    """2 failures for same provider → breaker NOT open (threshold is 3)."""
    mod = pytest.importorskip("app.services.ioc_enrichment.circuit_breaker")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_breaker_open_check():
    """is_breaker_open returns True immediately after breaker key is SET."""
    mod = pytest.importorskip("app.services.ioc_enrichment.circuit_breaker")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_breaker_reset_on_success():
    """record_success DELetes the failure counter key → failure count back to 0."""
    mod = pytest.importorskip("app.services.ioc_enrichment.circuit_breaker")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_breaker_auto_resets_after_ttl():
    """After the enrich:cb key TTL expires, is_breaker_open returns False (half-open)."""
    mod = pytest.importorskip("app.services.ioc_enrichment.circuit_breaker")
    assert False, "stub"
