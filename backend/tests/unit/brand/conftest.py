"""Brand unit test fixtures — stubs extended by Wave 1+ plans.

Provides:
  fake_crtsh_response      — extended by plan 12-02 (crtsh_client tests)
  stubbed_dnstwist_popen   — extended by plan 12-02 (dnstwist_parser tests)
  redis_mock               — extended by plan 12-03 (preview cache tests)
  golden_dnstwist_json     — loads golden dnstwist permutations fixture
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "dnstwist_json"


@pytest.fixture
def fake_crtsh_response():
    """Stub — extended by plan 12-02 (crtsh_client tests)."""
    return None


@pytest.fixture
def stubbed_dnstwist_popen(monkeypatch):
    """Stub — extended by plan 12-02 (dnstwist_parser tests)."""
    return None


@pytest.fixture
def redis_mock(monkeypatch):
    """Stub — extended by plan 12-03 (preview cache tests)."""
    return None


@pytest.fixture
def golden_dnstwist_json():
    return json.loads((FIXTURES_DIR / "sample_permutations.json").read_text())
