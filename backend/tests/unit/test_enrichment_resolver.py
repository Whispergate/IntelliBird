"""Unit test stubs — enrichment API key resolver.

Wave 0: all tests are xfail stubs. They will go GREEN when
plan 23-03 ships the providers CRUD + resolver module.

Resolver logic (per CONTEXT.md):
  - Per-project row exists + enabled → use per-project key
  - Per-project row absent but global row exists + enabled → fall back to global key
  - enabled=False → skip provider
  - Shodan: disabled by default (no key configured → skipped)

Requirement coverage: ENRICH-01 (per-project provider key management).
"""
from __future__ import annotations

import pytest

@pytest.mark.xfail(reason="not yet implemented —")
def test_global_fallback():
    """When per-project row is absent and global row exists + enabled, resolver returns global key."""
    mod = pytest.importorskip("app.services.ioc_enrichment.resolver")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_per_project_preferred():
    """When per-project row exists + enabled, resolver returns per-project key (not global)."""
    mod = pytest.importorskip("app.services.ioc_enrichment.resolver")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_disabled_provider_skipped():
    """Provider row with enabled=False → resolver does not return a key for that provider."""
    mod = pytest.importorskip("app.services.ioc_enrichment.resolver")
    assert False, "stub"


@pytest.mark.xfail(reason="not yet implemented —")
def test_shodan_disabled_by_default():
    """No Shodan key configured → Shodan is skipped (not returned by resolver)."""
    mod = pytest.importorskip("app.services.ioc_enrichment.resolver")
    assert False, "stub"
