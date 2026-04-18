"""MaxMind reader + LRU cache tests — plan 06-01 target (MAP-05)."""
from __future__ import annotations

import pytest

from app.services import geo as geo_module
from app.services.geo import resolve_geo


# ---------------------------------------------------------------------------
# Stub reader helpers
# ---------------------------------------------------------------------------


class _StubLocation:
    def __init__(self, lat, lon):
        self.latitude = lat
        self.longitude = lon


class _StubCountry:
    def __init__(self, cc):
        self.iso_code = cc


class _StubResponse:
    def __init__(self, lat, lon, cc):
        self.location = _StubLocation(lat, lon)
        self.country = _StubCountry(cc)


class StubReader:
    def __init__(self, response=None, raise_exc=None):
        self.response = response
        self.raise_exc = raise_exc
        self.calls: list[str] = []

    def city(self, ip: str):
        self.calls.append(ip)
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.response


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_reader_state():
    """Reset module-level reader state and LRU cache between tests."""
    # Save original state
    orig_reader = geo_module._reader
    orig_attempted = geo_module._reader_attempted
    yield
    # Restore state and clear cache
    geo_module._reader = orig_reader
    geo_module._reader_attempted = orig_attempted
    geo_module._lookup_ip.cache_clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_resolve_geo_no_mmdb_returns_none(monkeypatch, tmp_path):
    """GEOLITE_PATH pointing at a nonexistent file → (None, None, None); warning logged once."""
    import structlog.testing

    nonexistent = str(tmp_path / "missing.mmdb")
    monkeypatch.setenv("GEOLITE_PATH", nonexistent)

    # Force re-attempt on next call
    geo_module._reader = None
    geo_module._reader_attempted = False

    raw_stix = {"objects": [{"type": "ipv4-addr", "value": "8.8.8.8"}]}

    with structlog.testing.capture_logs() as cap:
        result1 = resolve_geo(raw_stix)
        result2 = resolve_geo(raw_stix)

    assert result1 == (None, None, None)
    assert result2 == (None, None, None)

    # Warning should have been emitted exactly once
    warnings = [e for e in cap if e.get("event") == "maxmind_db_missing"]
    assert len(warnings) == 1, f"Expected 1 maxmind_db_missing warning, got {len(warnings)}"


def test_maxmind_lookup_returns_coords(monkeypatch):
    """Stub reader returning valid coords → resolve_geo returns those coords."""
    stub = StubReader(response=_StubResponse(40.7, -74.0, "US"))
    monkeypatch.setattr("app.services.geo._get_reader", lambda: stub)

    raw_stix = {"objects": [{"type": "ipv4-addr", "value": "8.8.8.8"}]}
    result = resolve_geo(raw_stix)
    assert result == (40.7, -74.0, "US")


def test_cidr_ip_stripped_before_lookup(monkeypatch):
    """CIDR-suffixed IP value is stripped to plain IP before MaxMind lookup."""
    stub = StubReader(response=_StubResponse(1.0, 2.0, "DE"))
    monkeypatch.setattr("app.services.geo._get_reader", lambda: stub)

    raw_stix = {"objects": [{"type": "ipv4-addr", "value": "192.0.2.1/24"}]}
    resolve_geo(raw_stix)

    assert stub.calls == ["192.0.2.1"], f"Expected stripped IP, got {stub.calls}"


def test_lru_cache_hits_on_repeat_ip(monkeypatch):
    """Same IP queried twice → reader.city called exactly once (cache hit on second)."""
    stub = StubReader(response=_StubResponse(51.5, -0.1, "GB"))
    monkeypatch.setattr("app.services.geo._get_reader", lambda: stub)

    raw_stix = {"objects": [{"type": "ipv4-addr", "value": "1.2.3.4"}]}

    resolve_geo(raw_stix)
    resolve_geo(raw_stix)

    assert len(stub.calls) == 1, (
        f"reader.city should be called once (LRU cache hit on second), got {len(stub.calls)}"
    )


def test_address_not_found_returns_none(monkeypatch):
    """AddressNotFoundError from reader.city → resolve_geo returns (None, None, None)."""
    import geoip2.errors

    stub = StubReader(raise_exc=geoip2.errors.AddressNotFoundError("not found"))
    monkeypatch.setattr("app.services.geo._get_reader", lambda: stub)

    raw_stix = {"objects": [{"type": "ipv4-addr", "value": "192.0.2.0"}]}
    result = resolve_geo(raw_stix)
    assert result == (None, None, None)
