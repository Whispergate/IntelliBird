"""Unit test stubs - IOC enrichment normalization.

Wave 0: all tests are xfail stubs. They will go GREEN when
plan 23-02 ships the enrichment service layer.

Requirement coverage: ENRICH-02 (normalized indicator as cache key).
"""
from __future__ import annotations

import pytest

@pytest.mark.xfail(reason="not yet implemented -")
def test_ip_normalised_key():
    """normalized_indicator for IOC type=ip uses ioc.normalized_value as cache key suffix."""
    pytest.importorskip("app.services.ioc_enrichment.normalise")
    # e.g. ioc.type='ip', ioc.normalized_value='1.2.3.4' → cache key suffix '1.2.3.4'
    assert False, "stub - implement after 23-02 ships normalise module"


@pytest.mark.xfail(reason="not yet implemented -")
def test_domain_normalised_key():
    """normalized_indicator for IOC type=domain uses ioc.normalized_value as cache key suffix."""
    pytest.importorskip("app.services.ioc_enrichment.normalise")
    assert False, "stub - implement after 23-02 ships normalise module"


@pytest.mark.xfail(reason="not yet implemented -")
def test_hash_normalised_key():
    """sha256/sha1/md5 IOC types all produce unique, non-colliding cache key suffixes."""
    pytest.importorskip("app.services.ioc_enrichment.normalise")
    assert False, "stub - implement after 23-02 ships normalise module"
