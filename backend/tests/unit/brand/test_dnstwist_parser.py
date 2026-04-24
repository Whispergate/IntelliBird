"""Tests for app.services.dnstwist_parser — defensive key access + lookup_success derivation.

Activated by plan 12-02 (Wave 2 service primitives).

Key shape reference: docs/research/dnstwist-key-verification.md
"""
from __future__ import annotations

import os

# Pydantic-settings singleton bootstrap.
os.environ.setdefault("SECRET_KEY", "x" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "y" * 64)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest

from app.services.dnstwist_parser import parse_dnstwist_output, parse_permutation


# ---------------------------------------------------------------------------
# Defensive key access — canonical `domain` + belt-and-braces hyphen/underscore
# ---------------------------------------------------------------------------


def test_parse_permutation_handles_plain_domain_key():
    # Canonical dnstwist 20250130 form — single `domain` key.
    perm = {
        "fuzzer": "addition",
        "domain": "googleb.com",
        "dns_a": ["1.2.3.4"],
    }
    out = parse_permutation(perm)
    assert out is not None
    assert out["matched_value"] == "googleb.com"


def test_parse_permutation_handles_hyphen_key():
    # Defensive fallback for future version drift.
    perm = {
        "fuzzer": "addition",
        "domain-name": "hyphen.com",
        "dns_a": ["1.2.3.4"],
    }
    out = parse_permutation(perm)
    assert out is not None
    assert out["matched_value"] == "hyphen.com"


def test_parse_permutation_handles_underscore_key():
    perm = {
        "fuzzer": "addition",
        "domain_name": "under.com",
        "dns_a": ["1.2.3.4"],
    }
    out = parse_permutation(perm)
    assert out is not None
    assert out["matched_value"] == "under.com"


# ---------------------------------------------------------------------------
# lookup_success derivation — has_a OR has_ns, treating !ServFail + '' as no-data
# ---------------------------------------------------------------------------


def test_lookup_success_true_when_dns_a_present():
    perm = {"fuzzer": "addition", "domain": "x.com", "dns_a": ["1.2.3.4"]}
    out = parse_permutation(perm)
    assert out is not None
    assert out["lookup_success"] is True


def test_lookup_success_true_when_only_dns_ns():
    perm = {"fuzzer": "addition", "domain": "x.com", "dns_ns": ["ns1.x.com"]}
    out = parse_permutation(perm)
    assert out is not None
    assert out["lookup_success"] is True


def test_lookup_success_false_when_only_dns_mx():
    # MX-only is NOT enough — lookup_success requires A or NS per plan.
    perm = {"fuzzer": "addition", "domain": "x.com", "dns_mx": ["mx.x.com"]}
    out = parse_permutation(perm)
    assert out is not None
    assert out["lookup_success"] is False


def test_lookup_success_false_when_all_servfail():
    # Unresolved DNS surfaces as ["!ServFail"] per docs/research/dnstwist-key-verification.md.
    perm = {
        "fuzzer": "addition",
        "domain": "google4.com",
        "dns_a": ["!ServFail"],
        "dns_aaaa": ["!ServFail"],
        "dns_ns": ["!ServFail"],
    }
    out = parse_permutation(perm)
    assert out is not None
    assert out["lookup_success"] is False


def test_lookup_success_treats_empty_string_as_no_data():
    perm = {
        "fuzzer": "addition",
        "domain": "x.com",
        "dns_a": [""],
        "dns_ns": [""],
        "dns_mx": ["mx.x.com"],  # kept so the row is not filtered out
    }
    out = parse_permutation(perm)
    assert out is not None
    assert out["lookup_success"] is False


# ---------------------------------------------------------------------------
# Filtering — unregistered rows return None
# ---------------------------------------------------------------------------


def test_returns_none_when_no_dns_records():
    perm = {"fuzzer": "addition", "domain": "x.com"}
    assert parse_permutation(perm) is None


def test_returns_none_when_no_domain():
    perm = {"fuzzer": "addition", "dns_a": ["1.2.3.4"]}
    assert parse_permutation(perm) is None


def test_skips_original_row_in_parse_output():
    payload = [
        {"fuzzer": "*original", "domain": "x.com", "dns_a": ["1.2.3.4"]},
        {"fuzzer": "addition", "domain": "xx.com", "dns_a": ["5.6.7.8"]},
    ]
    out = parse_dnstwist_output(payload)
    values = [e["matched_value"] for e in out]
    assert "x.com" not in values
    assert "xx.com" in values


# ---------------------------------------------------------------------------
# Metadata passthrough
# ---------------------------------------------------------------------------


def test_extract_metadata_includes_fuzzer_dns_mx():
    perm = {
        "fuzzer": "homoglyph",
        "domain": "x.com",
        "dns_a": ["1.2.3.4"],
        "dns_aaaa": ["::1"],
        "dns_mx": ["mx.x.com"],
        "dns_ns": ["ns.x.com"],
    }
    out = parse_permutation(perm)
    assert out is not None
    assert out["fuzzer"] == "homoglyph"
    assert out["dns_mx"] == ["mx.x.com"]
    assert out["dns_a"] == ["1.2.3.4"]
    assert "dns_aaaa" in out
    assert "dns_ns" in out


# ---------------------------------------------------------------------------
# Golden fixture — full-DNS / partial-DNS / all-ServFail
# ---------------------------------------------------------------------------


def test_parse_dnstwist_output_against_golden(golden_dnstwist_json):
    out = parse_dnstwist_output(golden_dnstwist_json)
    # Golden has 3 rows: full-DNS googleb, partial googlec, all-ServFail google4.
    # All have DNS record keys so none are filtered out.
    assert len(out) == 3
    by_domain = {e["matched_value"]: e for e in out}
    # googleb.com — full DNS → lookup_success=True
    assert by_domain["googleb.com"]["lookup_success"] is True
    # googlec.com — A + NS only → lookup_success=True
    assert by_domain["googlec.com"]["lookup_success"] is True
    # google4.com — all !ServFail → lookup_success=False
    assert by_domain["google4.com"]["lookup_success"] is False
