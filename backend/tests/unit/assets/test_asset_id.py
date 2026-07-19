# Owned by: 12.1-03-PLAN
"""Unit tests for asset_id_for + bucket_for_type (Task 1)."""
from __future__ import annotations

import hashlib
import re

from app.services.assets_query import asset_id_for, bucket_for_type


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def test_asset_id_is_64_char_lowercase_hex():
    out = asset_id_for("DNS_NAME", "sub.example.com")
    assert _HEX64.match(out), f"expected 64-char lowercase hex, got: {out!r}"


def test_asset_id_is_deterministic():
    a = asset_id_for("DNS_NAME", "sub.example.com")
    b = asset_id_for("DNS_NAME", "sub.example.com")
    c = asset_id_for("DNS_NAME", "sub.example.com")
    assert a == b == c


def test_asset_id_is_type_sensitive():
    # Same value, different bbot_event_type -> different id
    ip = asset_id_for("IP_ADDRESS", "10.0.0.1")
    dns = asset_id_for("DNS_NAME", "10.0.0.1")
    assert ip != dns


def test_asset_id_is_case_sensitive():
    upper = asset_id_for("DNS_NAME", "aB.example.com")
    lower = asset_id_for("DNS_NAME", "ab.example.com")
    assert upper != lower


def test_asset_id_matches_direct_sha256():
    """Regression lock: concatenation order is bbot_event_type + canonical_target,
    no separator, UTF-8 (research Pitfall 4)."""
    expected = hashlib.sha256(b"DNS_NAMEexample.com").hexdigest()
    assert asset_id_for("DNS_NAME", "example.com") == expected


def test_bucket_for_type_mapping():
    assert bucket_for_type("DNS_NAME") == "DOMAINS"
    assert bucket_for_type("IP_ADDRESS") == "IPS"
    assert bucket_for_type("OPEN_TCP_PORT") == "OPEN_PORTS"
    assert bucket_for_type("OPEN_UDP_PORT") == "OPEN_PORTS"
    assert bucket_for_type("URL") == "URLS"
    assert bucket_for_type("URL_UNVERIFIED") == "URLS"
    assert bucket_for_type("TECHNOLOGY") == "TECHNOLOGIES"
    assert bucket_for_type("WAF") == "TECHNOLOGIES"
    assert bucket_for_type("EMAIL_ADDRESS") == "IDENTITIES"
    assert bucket_for_type("USERNAME") == "IDENTITIES"
    assert bucket_for_type("FINDING") == "OTHER"
    assert bucket_for_type("SOMETHING_NEW_IN_BBOT_3") == "OTHER"
