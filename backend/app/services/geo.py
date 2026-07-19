""" geo resolution -.. (MAP-05).

resolve_geo(raw_stix) returns (lat, lon, country_code) using:
 1. STIX location SDO latitude/longitude/country
 2. MaxMind GeoLite2 City lookup on first IP observable
 3. (None, None, None) if nothing resolves

The MMDB file at GEOLITE_PATH is optional - absent file logs a
single warning on first attempt and all subsequent calls short-circuit.
"""
from __future__ import annotations

import functools
import os
from typing import Any, Optional

import structlog

log = structlog.get_logger(__name__)

# Module-level reader state. _reader_attempted is set to True the first time
# _get_reader is called, preventing repeated filesystem checks.
_reader: Any = None
_reader_attempted: bool = False


def _get_reader() -> Any:
    """Lazily load the MaxMind GeoLite2 City reader exactly once per process.

 Returns the geoip2.database.Reader instance on success, or None if the
 MMDB file is absent or the library is unavailable.
"""
    global _reader, _reader_attempted
    if _reader_attempted:
        return _reader
    _reader_attempted = True
    path = os.environ.get("GEOLITE_PATH", "/app/geolite/GeoLite2-City.mmdb")
    try:
        import geoip2.database  # lazy - keeps module loadable without geoip2 installed
        _reader = geoip2.database.Reader(path)
        log.info("maxmind_db_loaded", path=path)
    except FileNotFoundError:
        log.warning("maxmind_db_missing", path=path)
        _reader = None
    except Exception as exc:  # noqa: BLE001 - corrupted DB, missing lib, etc.
        log.warning("maxmind_db_load_failed", path=path, error=str(exc))
        _reader = None
    return _reader


@functools.lru_cache(maxsize=10000)
def _lookup_ip(ip: str) -> Optional[tuple[float, float, str | None]]:
    """Return (lat, lon, country_code) for a plain IP string, or None.

 Caches results to avoid repeated MMDB reads for the same IP. The
 caller is responsible for stripping any CIDR suffix before calling.

 Raises nothing - AddressNotFoundError and all other geoip2 errors are
 caught and converted to None.
"""
    reader = _get_reader()
    if reader is None:
        return None
    try:
        response = reader.city(ip)
    except Exception:  # noqa: BLE001 - AddressNotFoundError + any geoip2 error
        return None
    lat = getattr(response.location, "latitude", None)
    lon = getattr(response.location, "longitude", None)
    cc = getattr(response.country, "iso_code", None)
    if lat is None or lon is None:
        return None
    return float(lat), float(lon), cc


def _extract_stix_location(
    raw_stix: dict | None,
) -> Optional[tuple[float, float, str | None]]:
    """Return (lat, lon, country_code) from the first STIX location SDO that
 has both latitude and longitude, or None if no usable location is found.

 country may be absent in a location SDO - that is fine per STIX 2.1.
"""
    if not isinstance(raw_stix, dict):
        return None
    objects = raw_stix.get("objects")
    if not isinstance(objects, list):
        return None
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        if obj.get("type") != "location":
            continue
        lat = obj.get("latitude")
        lon = obj.get("longitude")
        if lat is None or lon is None:
            continue
        return float(lat), float(lon), obj.get("country")
    return None


def _extract_ips_from_stix(raw_stix: dict | None) -> list[str]:
    """Return a list of IP value strings from STIX ipv4-addr and ipv6-addr
 observables in bundle order.

 Values may include CIDR suffixes (e.g. ``192.0.2.1/24``) per STIX
 flexibility - callers are expected to strip them before lookup.
"""
    if not isinstance(raw_stix, dict):
        return []
    objects = raw_stix.get("objects")
    if not isinstance(objects, list):
        return []
    out: list[str] = []
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        if obj.get("type") in ("ipv4-addr", "ipv6-addr"):
            v = obj.get("value")
            if isinstance(v, str):
                out.append(v)
    return out


def resolve_geo(
    raw_stix: dict | None,
) -> tuple[float | None, float | None, str | None]:
    """Resolve geographic coordinates for an event using precedence.

 Resolution order:
 1. STIX location SDO (latitude + longitude + optional country)
 2. MaxMind GeoLite2 City lookup on first IP observable in bundle
 3. (None, None, None) - coordinates unknown

 CIDR suffixes on IP values are stripped automatically before the
 MaxMind lookup so geoip2 does not raise AddressNotFoundError.

 Never raises - all failure modes (absent MMDB, unknown IP, bad STIX
 shape, None input) are handled and produce (None, None, None).
"""
    stix_hit = _extract_stix_location(raw_stix)
    if stix_hit is not None:
        return stix_hit
    for ip in _extract_ips_from_stix(raw_stix):
        ip_clean = ip.split("/")[0]
        hit = _lookup_ip(ip_clean)
        if hit is not None:
            return hit
    return None, None, None
