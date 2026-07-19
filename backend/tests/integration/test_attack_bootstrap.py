"""ATT&CK bootstrap - three-tier fallback coverage.

These tests use the bundled snapshots and httpx/TAXII monkeypatching;
they do not require network access.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

from app.workers import bootstrap  # noqa: E402


@pytest.fixture
def fake_bundle() -> dict:
    return {
        "type": "bundle",
        "id": "bundle--test",
        "objects": [
            {
                "type": "attack-pattern",
                "spec_version": "2.1",
                "id": "attack-pattern--test-001",
                "name": "Test Technique",
                "external_references": [
                    {"source_name": "mitre-attack", "external_id": "T9999"}
                ],
                "kill_chain_phases": [
                    {"kill_chain_name": "mitre-attack", "phase_name": "execution"}
                ],
            }
        ],
    }


def test_taxii_path(monkeypatch, fake_bundle):
    """Primary TAXII path returns a bundle."""
    monkeypatch.setattr(bootstrap, "_fetch_taxii", lambda m, timeout=30.0: fake_bundle)
    result = bootstrap.fetch_with_fallback("enterprise")
    assert result == fake_bundle


def test_github_fallback(monkeypatch, fake_bundle):
    """TAXII fails → GitHub succeeds."""
    monkeypatch.setattr(bootstrap, "_fetch_taxii", lambda m, timeout=30.0: None)
    monkeypatch.setattr(bootstrap, "_fetch_github", lambda m, timeout=60.0: fake_bundle)
    result = bootstrap.fetch_with_fallback("ics")
    assert result == fake_bundle


def test_bundled_fallback(monkeypatch):
    """Both TAXII and GitHub fail → bundled snapshot used."""
    monkeypatch.setattr(bootstrap, "_fetch_taxii", lambda m, timeout=30.0: None)
    monkeypatch.setattr(bootstrap, "_fetch_github", lambda m, timeout=60.0: None)
    # Real bundled file from Task 3.1 - must exist and be valid JSON
    result = bootstrap.fetch_with_fallback("mobile")
    assert result is not None, "bundled mobile snapshot missing"
    assert result.get("type") == "bundle"
    assert any(o.get("type") == "attack-pattern" for o in result.get("objects", []))
