"""Unit tests for TAXII 2.1 router — Phase 26 / TAXII-01, TAXII-05.

Wave 0 stubs. All tests skip until router is implemented in plan 26-04.
"""
from __future__ import annotations
import pytest


@pytest.mark.skip(reason="stub — implement in plan 26-04")
def test_discovery_response():
    """TAXII-01: GET /taxii2/ returns spec-correct JSON with title + api_roots."""
    raise NotImplementedError


@pytest.mark.skip(reason="stub — implement in plan 26-04")
def test_discovery_requires_auth():
    """TAXII-01: GET /taxii2/ without credentials returns 401."""
    raise NotImplementedError


@pytest.mark.skip(reason="stub — implement in plan 26-04")
def test_content_type_header():
    """TAXII-05: Every TAXII response carries Content-Type: application/taxii+json;version=2.1."""
    raise NotImplementedError


@pytest.mark.skip(reason="stub — implement in plan 26-04")
def test_page_cap_100():
    """TAXII-05: Requesting limit=200 returns at most 100 objects + more=true."""
    raise NotImplementedError
