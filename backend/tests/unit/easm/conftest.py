"""EASM unit test fixtures — stub stubs extended by Wave 1+ plans.

Provides:
  fake_docker     — extended by plans 11-04/11-05 when bbot_runner lands
  stubbed_popen   — extended by plans 11-04/11-05
  redis_mock      — extended by plan 11-04 (semaphore tests)
  bbot_ndjson_passive       — loads golden passive_scan.ndjson fixture
  bbot_ndjson_vulnerability — loads golden vulnerability_finding.ndjson fixture
"""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "bbot_ndjson"


@pytest.fixture
def fake_docker(monkeypatch):
    """Stub — extended by plans 11-04/11-05 when bbot_runner lands."""
    return None


@pytest.fixture
def stubbed_popen(monkeypatch):
    """Stub — extended by plans 11-04/11-05."""
    return None


@pytest.fixture
def redis_mock(monkeypatch):
    """Stub — extended by plan 11-04 (semaphore tests)."""
    return None


@pytest.fixture
def bbot_ndjson_passive():
    return (FIXTURES_DIR / "passive_scan.ndjson").read_text()


@pytest.fixture
def bbot_ndjson_vulnerability():
    return (FIXTURES_DIR / "vulnerability_finding.ndjson").read_text()
