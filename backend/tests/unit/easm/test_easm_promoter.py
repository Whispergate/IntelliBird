"""Unit tests for easm_promoter.py — allowlist promotion + STIX mapping.

Plan 11-03 / EASM-06 / H-4 feed contamination prevention.

Tests use in-memory dataclass stubs for EASMFinding + EASMScan (no DB).
The promoter is a pure function — no session required.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest

from app.services.easm_promoter import (
    FINDING_MIN_SEVERITY,
    PROMOTION_ALLOWLIST,
    STIX_TYPE_BY_BBOT_TYPE,
    promote_finding_to_event,
    should_promote,
)


# ---------------------------------------------------------------------------
# In-memory stubs — mirrors EASMFinding / EASMScan ORM shape without DB
# ---------------------------------------------------------------------------

@dataclass
class _F:
    """Stub for EASMFinding."""
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    project_id: uuid.UUID = field(default_factory=uuid.uuid4)
    bbot_event_type: str = "FINDING"
    canonical_target: str = "sub.example.com"
    severity: str | None = None
    module: str = "nuclei"
    raw_bbot: dict = field(default_factory=lambda: {"data": {"description": "test vuln", "severity": "HIGH"}})
    content_hash: str = "abc123"


@dataclass
class _S:
    """Stub for EASMScan."""
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    project_id: uuid.UUID = field(default_factory=uuid.uuid4)


# ---------------------------------------------------------------------------
# should_promote — allowlist behaviour
# ---------------------------------------------------------------------------

def test_should_promote_vulnerability():
    assert should_promote("VULNERABILITY", None) is True


def test_should_promote_subdomain_takeover():
    assert should_promote("SUBDOMAIN_TAKEOVER_CANDIDATE", None) is True


def test_should_promote_technology():
    assert should_promote("TECHNOLOGY", None) is True


def test_should_promote_finding_high():
    assert should_promote("FINDING", "HIGH") is True


def test_should_promote_finding_critical():
    assert should_promote("FINDING", "CRITICAL") is True


def test_should_promote_finding_medium_rejected():
    assert should_promote("FINDING", "MEDIUM") is False


def test_should_promote_finding_low_rejected():
    assert should_promote("FINDING", "LOW") is False


def test_should_promote_finding_no_severity_rejected():
    assert should_promote("FINDING", None) is False


def test_should_promote_dns_name_rejected():
    assert should_promote("DNS_NAME", None) is False


def test_should_promote_ip_address_rejected():
    assert should_promote("IP_ADDRESS", None) is False


def test_should_promote_open_port_rejected():
    assert should_promote("OPEN_PORT", None) is False


def test_should_promote_url_rejected():
    assert should_promote("URL", None) is False


# ---------------------------------------------------------------------------
# promote_finding_to_event — STIX type mapping
# ---------------------------------------------------------------------------

def test_promote_vulnerability_produces_vulnerability_stix_type():
    f = _F(bbot_event_type="VULNERABILITY", severity=None,
           raw_bbot={"data": {"description": "SQLi on /login", "severity": None, "url": "https://example.com/login"}})
    s = _S()
    kwargs = promote_finding_to_event(f, s)
    assert kwargs["stix_type"] == "vulnerability"


def test_promote_technology_produces_observed_data_stix_type():
    f = _F(bbot_event_type="TECHNOLOGY", severity=None,
           raw_bbot={"data": {"technology": "Apache", "version": "2.4.51"}})
    s = _S()
    kwargs = promote_finding_to_event(f, s)
    assert kwargs["stix_type"] == "observed-data"


def test_promote_takeover_produces_indicator_stix_type():
    f = _F(bbot_event_type="SUBDOMAIN_TAKEOVER_CANDIDATE", severity=None,
           raw_bbot={"data": {"description": "Unclaimed S3 bucket"}})
    s = _S()
    kwargs = promote_finding_to_event(f, s)
    assert kwargs["stix_type"] == "indicator"


def test_promote_finding_high_produces_indicator_stix_type():
    f = _F(bbot_event_type="FINDING", severity="HIGH",
           raw_bbot={"data": {"description": "Exposed admin panel", "severity": "HIGH"}})
    s = _S()
    kwargs = promote_finding_to_event(f, s)
    assert kwargs["stix_type"] == "indicator"


# ---------------------------------------------------------------------------
# promote_finding_to_event — ValueError on non-promotable types
# ---------------------------------------------------------------------------

def test_promote_non_promotable_raises_valueerror():
    f = _F(bbot_event_type="DNS_NAME", severity=None, raw_bbot={"data": "sub.example.com"})
    s = _S()
    with pytest.raises(ValueError, match="not promotable"):
        promote_finding_to_event(f, s)


# ---------------------------------------------------------------------------
# promote_finding_to_event — defensive BBOT data access (PITFALLS §Pitfall 6)
# ---------------------------------------------------------------------------

def test_promote_handles_non_dict_raw_bbot_data():
    """VULNERABILITY finding with raw_bbot.data as non-dict must not crash."""
    f = _F(
        bbot_event_type="VULNERABILITY",
        severity=None,
        raw_bbot={"data": "plain string not a dict"},
        canonical_target="sub.example.com",
    )
    s = _S()
    # Should not raise — defensive access falls back gracefully
    kwargs = promote_finding_to_event(f, s)
    assert kwargs["stix_type"] == "vulnerability"


# ---------------------------------------------------------------------------
# promote_finding_to_event — provenance fields
# ---------------------------------------------------------------------------

def test_promoted_event_has_source_type_bbot():
    f = _F(bbot_event_type="VULNERABILITY", severity=None,
           raw_bbot={"data": {"description": "test", "url": ""}})
    s = _S()
    kwargs = promote_finding_to_event(f, s)
    assert kwargs["source_type"] == "bbot"


def test_promoted_event_has_easm_scan_id_set():
    scan = _S()
    f = _F(bbot_event_type="VULNERABILITY", severity=None,
           raw_bbot={"data": {"description": "test", "url": ""}})
    kwargs = promote_finding_to_event(f, scan)
    assert kwargs["easm_scan_id"] == scan.id


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------

def test_promotion_allowlist_contains_expected_types():
    assert "VULNERABILITY" in PROMOTION_ALLOWLIST
    assert "SUBDOMAIN_TAKEOVER_CANDIDATE" in PROMOTION_ALLOWLIST
    assert "TECHNOLOGY" in PROMOTION_ALLOWLIST
    # Low-confidence types must NOT be in the allowlist
    assert "DNS_NAME" not in PROMOTION_ALLOWLIST
    assert "IP_ADDRESS" not in PROMOTION_ALLOWLIST


def test_finding_min_severity_contains_high_and_critical():
    assert "HIGH" in FINDING_MIN_SEVERITY
    assert "CRITICAL" in FINDING_MIN_SEVERITY
    assert "MEDIUM" not in FINDING_MIN_SEVERITY


def test_stix_type_map_covers_all_promotable_types():
    for t in ("VULNERABILITY", "TECHNOLOGY", "SUBDOMAIN_TAKEOVER_CANDIDATE", "FINDING"):
        assert t in STIX_TYPE_BY_BBOT_TYPE
