"""Per-type content_hash formulas for INGR-03 dedup.

: RSS / STIX / NVD each have their own natural-identity hash.
: Field separator is ASCII Unit Separator 0x1F - avoids injection via `|` or `:`.
: Hash computed in Python before insert, stored as lowercase hex in events.content_hash.
"""
from __future__ import annotations

import hashlib
import re


from app.ingest.dedup import SEP, nvd_content_hash, rss_content_hash, taxii_content_hash

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def test_separator_is_unit_separator() -> None:
    assert SEP == "\x1f"
    assert ord(SEP) == 31


def test_rss_hash_formula() -> None:
    h = rss_content_hash("src-uuid", "https://ex/a", "title")
    expected = hashlib.sha256("src-uuid\x1fhttps://ex/a\x1ftitle".encode()).hexdigest()
    assert h == expected
    assert HEX64.match(h)


def test_taxii_hash_formula() -> None:
    h = taxii_content_hash("src", "indicator--abc", "2026-04-07T12:00:00.000Z")
    expected = hashlib.sha256("src\x1findicator--abc\x1f2026-04-07T12:00:00.000Z".encode()).hexdigest()
    assert h == expected


def test_nvd_hash_formula() -> None:
    h = nvd_content_hash("src", "CVE-2024-1", "2026-04-10T12:00:00.000")
    expected = hashlib.sha256("src\x1fCVE-2024-1\x1f2026-04-10T12:00:00.000".encode()).hexdigest()
    assert h == expected


def test_injection_resistance() -> None:
    """Printable `|` in any field cannot collide with a different-field input."""
    a = rss_content_hash("a|b", "c|d", "e|f")
    b = rss_content_hash("a", "b|c|d", "e|f")
    assert a != b


def test_hash_determinism() -> None:
    inputs = ("src", "link", "title")
    first = rss_content_hash(*inputs)
    for _ in range(100):
        assert rss_content_hash(*inputs) == first
    # Order matters - swapping link and title produces a different hash
    assert rss_content_hash("src", "title", "link") != first


def test_hash_is_hex_lowercase() -> None:
    for fn, args in [
        (rss_content_hash, ("s", "l", "t")),
        (taxii_content_hash, ("s", "i", "m")),
        (nvd_content_hash, ("s", "c", "m")),
    ]:
        assert HEX64.match(fn(*args)), f"{fn.__name__} did not return 64-char lowercase hex"
