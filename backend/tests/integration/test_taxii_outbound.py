"""Integration tests for TAXII 2.1 outbound server — Phase 26 / TAXII-02..05.

Wave 0 stubs. All tests skip until router + service layer implemented.
Uses testcontainer-based DB matching existing integration test pattern.
"""
from __future__ import annotations
import pytest


@pytest.mark.integration
@pytest.mark.skip(reason="stub — implement in plan 26-04")
async def test_collections_acl():
    """TAXII-02: Collections list returns only collections the partner key has ACL for."""
    raise NotImplementedError


@pytest.mark.integration
@pytest.mark.skip(reason="stub — implement in plan 26-04")
async def test_objects_pagination():
    """TAXII-02: Objects endpoint returns paginated STIX envelope with more=True + next cursor when >100 events."""
    raise NotImplementedError


@pytest.mark.integration
@pytest.mark.skip(reason="stub — implement in plan 26-04")
async def test_key_revocation_instant():
    """TAXII-03: Revoking a partner key returns 401 on the very next request (no cache lag)."""
    raise NotImplementedError


@pytest.mark.integration
@pytest.mark.skip(reason="stub — implement in plan 26-04")
async def test_rate_limit():
    """TAXII-03: Partner key with rate_limit_rpm=2 is rejected after 2 requests in the same minute window."""
    raise NotImplementedError


@pytest.mark.integration
@pytest.mark.skip(reason="stub — implement in plan 26-04")
async def test_tlp_acl_amber_filtered():
    """TAXII-04: Partner with tlp_max_level='green' receives no AMBER/RED events in objects response."""
    raise NotImplementedError


@pytest.mark.integration
@pytest.mark.skip(reason="stub — implement in plan 26-04")
async def test_tlp_acl_amber_visible():
    """TAXII-04: Partner with tlp_max_level='amber' receives AMBER events in objects response."""
    raise NotImplementedError
