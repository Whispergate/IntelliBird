"""resolve_geo STIX-location path --01 target (MAP-05)."""
from __future__ import annotations

import pytest

from app.services import geo as geo_module
from app.services.geo import (
    _extract_ips_from_stix,
    resolve_geo,
)


@pytest.fixture(autouse=True)
def _clear_lru_cache():
    yield
    geo_module._lookup_ip.cache_clear()


# ---------------------------------------------------------------------------
# _extract_stix_location helpers
# ---------------------------------------------------------------------------


def test_stix_location_preferred_over_ip(monkeypatch):
    """STIX location SDO coordinates take priority - MaxMind must not be called."""
    call_count = [0]

    def _fake_reader():
        call_count[0] += 1
        return None  # returning a reader here would mean MaxMind was consulted

    monkeypatch.setattr("app.services.geo._get_reader", _fake_reader)

    raw_stix = {
        "objects": [
            {"type": "location", "latitude": 51.5, "longitude": -0.1, "country": "GB"},
            {"type": "ipv4-addr", "value": "8.8.8.8"},
        ]
    }
    result = resolve_geo(raw_stix)
    assert result == (51.5, -0.1, "GB")
    assert call_count[0] == 0, "_get_reader should not be called when STIX location is present"


def test_stix_location_missing_lat_skipped():
    """A location SDO with only country (no lat/lon) is skipped; result is (None, None, None)."""
    raw_stix = {
        "objects": [
            {"type": "location", "country": "GB"},  # no latitude/longitude
        ]
    }
    result = resolve_geo(raw_stix)
    assert result == (None, None, None)


def test_resolve_geo_handles_none_raw_stix():
    """`resolve_geo(None)` returns (None, None, None) without raising."""
    assert resolve_geo(None) == (None, None, None)


def test_resolve_geo_handles_empty_bundle():
    """`resolve_geo({})` and `resolve_geo({"objects": []})` return (None, None, None)."""
    assert resolve_geo({}) == (None, None, None)
    assert resolve_geo({"objects": []}) == (None, None, None)


def test_extract_ips_from_stix_covers_ipv4_and_ipv6():
    """Bundle with one ipv4-addr and one ipv6-addr returns both value strings in order."""
    raw_stix = {
        "objects": [
            {"type": "ipv4-addr", "value": "1.2.3.4"},
            {"type": "ipv6-addr", "value": "2001:db8::1"},
        ]
    }
    ips = _extract_ips_from_stix(raw_stix)
    assert ips == ["1.2.3.4", "2001:db8::1"]


def test_extract_ips_ignores_non_address_objects():
    """Bundle with a threat-actor SDO and an ipv4-addr returns only the IP value."""
    raw_stix = {
        "objects": [
            {"type": "threat-actor", "name": "APT-X"},
            {"type": "ipv4-addr", "value": "10.0.0.1"},
        ]
    }
    ips = _extract_ips_from_stix(raw_stix)
    assert ips == ["10.0.0.1"]
