"""STIX 2.1 bundle → (ioc_type, raw_value) iterator (IOC-02).

Maps the eight atomic indicator/observed-data shapes documented in CONTEXT.md
§"STIX SDO mapping". Compound patterns (AND/OR/FOLLOWEDBY) are skipped - they
are rare in indicator feeds and outside 's scope (per RESEARCH.md).

Try a normal parse first; on any parse error we retry with `allow_custom=True`
so malformed bundles from third-party feeds still yield whatever we recognise.

NOTE: the installed `stix2` (3.x) does NOT accept a `strict` kwarg on
`parse()` - verified via `help(stix2.parse)`. The existing
`tiber/exporters/stix.py:143` usage already calls `stix2.parse(bundle_json,
allow_custom=True)` only and we mirror that here.
"""
from __future__ import annotations

import re
from typing import Iterator

import stix2

PATTERN_RE = re.compile(
    r"\[\s*(?P<type>[a-z0-9\-]+):(?P<prop>[a-zA-Z0-9.\-_]+)\s*=\s*'(?P<val>[^']+)'\s*\]"
)

STIX_TYPE_MAP: dict[tuple[str, str], str] = {
    ("ipv4-addr", "value"): "ip",
    ("ipv6-addr", "value"): "ipv6",
    ("domain-name", "value"): "domain",
    ("url", "value"): "url",
    ("file", "hashes.SHA-256"): "sha256",
    ("file", "hashes.SHA-1"): "sha1",
    ("file", "hashes.MD5"): "md5",
    ("email-addr", "value"): "email",
}


def parse_stix_bundle(bundle_json: dict) -> Iterator[tuple[str, str]]:
    """Yield (ioc_type, raw_value) tuples from a STIX 2.1 bundle dict.

    Indicators: regex over `pattern` extracts atomic `[type:prop='val']` shapes
    and maps via STIX_TYPE_MAP. Pattern types other than `stix` (e.g. `pcre`)
    are skipped.

    Observed-data: walks `objects[*]` for SCO shapes (ipv4-addr, ipv6-addr,
    domain-name, url, email-addr, file with SHA-256/SHA-1/MD5).
    """
    bundle = None
    try:
        bundle = stix2.parse(bundle_json, allow_custom=False)
    except Exception:  # noqa: BLE001 - STIXError + downstream validation errors
        try:
            bundle = stix2.parse(bundle_json, allow_custom=True)
        except Exception:  # noqa: BLE001
            bundle = None

    # Manual-walk fallback: third-party feeds (and test fixtures) sometimes
    # ship bundles whose ids don't satisfy stix2's UUID-suffix rule (e.g.
    # `bundle--1`). The atomic-extraction contract here only needs the raw
    # JSON object shape, so when stix2.parse rejects the bundle we walk
    # `bundle_json["objects"]` directly. This is also what
    # `getattr(bundle, "objects", [])` would return on a successful parse.
    if bundle is not None:
        objects_iter = getattr(bundle, "objects", []) or []
    else:
        objects_iter = bundle_json.get("objects", []) or []

    for obj in objects_iter:
        t = (
            obj.get("type")
            if isinstance(obj, dict)
            else getattr(obj, "type", None)
        )
        # Tolerate both dict-shape (manual walk) and SDO-class shape (stix2-parsed).
        _o_get = (
            (lambda k, default=None, _o=obj: _o.get(k, default))
            if isinstance(obj, dict)
            else (lambda k, default=None, _o=obj: getattr(_o, k, default))
        )
        if t == "indicator" and (_o_get("pattern_type", "stix") == "stix"):
            for m in PATTERN_RE.finditer(_o_get("pattern", "") or ""):
                key = (m.group("type"), m.group("prop"))
                if key in STIX_TYPE_MAP:
                    yield STIX_TYPE_MAP[key], m.group("val")
        elif t == "observed-data":
            scos = _o_get("objects", {}) or {}
            sco_iter = scos.values() if isinstance(scos, dict) else []
            for sco in sco_iter:
                # Tolerate both dict and SCO-class shapes.
                sco_type = (
                    sco.get("type")
                    if isinstance(sco, dict)
                    else getattr(sco, "type", None)
                )
                _get = (
                    (lambda k, default=None, _s=sco: _s.get(k, default))
                    if isinstance(sco, dict)
                    else (lambda k, default=None, _s=sco: getattr(_s, k, default))
                )
                if sco_type == "ipv4-addr":
                    val = _get("value")
                    if val:
                        yield "ip", val
                elif sco_type == "ipv6-addr":
                    val = _get("value")
                    if val:
                        yield "ipv6", val
                elif sco_type == "domain-name":
                    val = _get("value")
                    if val:
                        yield "domain", val
                elif sco_type == "url":
                    val = _get("value")
                    if val:
                        yield "url", val
                elif sco_type == "email-addr":
                    val = _get("value")
                    if val:
                        yield "email", val
                elif sco_type == "file":
                    hashes = _get("hashes") or {}
                    if not isinstance(hashes, dict):
                        # stix2 SCO objects may expose hashes via attribute.
                        try:
                            hashes = dict(hashes)
                        except Exception:  # noqa: BLE001
                            hashes = {}
                    for algo_key, algo_value in hashes.items():
                        mapped = {"SHA-256": "sha256", "SHA-1": "sha1", "MD5": "md5"}.get(
                            algo_key
                        )
                        if mapped and algo_value:
                            yield mapped, algo_value


__all__ = ["parse_stix_bundle", "STIX_TYPE_MAP", "PATTERN_RE"]
