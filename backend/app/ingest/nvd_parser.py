"""NVD CVE → canonical Event row + CveDetails row + optional ATT&CK links.

INGC-01: CVE fetched and persisted with normalised fields.
INGC-02: CVSS v3 score/vector, CPE match list, CWE ids in indexed cve_details columns.
INGC-03: attack.mitre.org/techniques/T#### URLs (or tag-based T#### alongside
 Exploit/VDB Entry tag) → attack_technique_tags with tag_source='feed_asserted'.
 analog: CVEs missing `id` or `lastModified` are dropped.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.ingest.dedup import nvd_content_hash

_STIX_TYPE = "x-nvd-cve"
_ATTACK_URL_PATTERN = re.compile(
    r"https?://attack\.mitre\.org/techniques/(T\d{4}(?:\.\d{3})?)",
    re.IGNORECASE,
)
_ATTACK_TAG_PATTERN = re.compile(r"^T\d{4}(?:\.\d{3})?$")
_EXPLOIT_TAGS: frozenset[str] = frozenset({"Exploit", "VDB Entry"})


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """Tolerant attribute/key access — NVD libs expose either shape."""
    if obj is None:
        return default
    try:
        v = getattr(obj, name)
    except AttributeError:
        try:
            v = obj[name]
        except (TypeError, KeyError):
            return default
    return v if v is not None else default


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    # NVD ISO strings lack timezone — treat as UTC.
    s = ts.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _first_english_description(cve: Any) -> str | None:
    for d in _attr(cve, "descriptions", []) or []:
        if _attr(d, "lang") == "en":
            return _attr(d, "value")
    return None


def _cvss_v3(cve: Any) -> tuple[float | None, str | None]:
    metrics = _attr(cve, "metrics")
    v31 = _attr(metrics, "cvssMetricV31", []) or []
    v30 = _attr(metrics, "cvssMetricV30", []) or []
    for entries in (v31, v30):
        for m in entries or []:
            data = _attr(m, "cvssData")
            if data is None:
                continue
            score = _attr(data, "baseScore")
            vector = _attr(data, "vectorString")
            if score is not None:
                return (float(score), vector)
    return (None, None)


def _cpe_match(cve: Any) -> list[dict] | None:
    """Flatten configurations[*].nodes[*].cpeMatch[*] → list of dicts."""
    out: list[dict] = []
    for cfg in _attr(cve, "configurations", []) or []:
        for node in _attr(cfg, "nodes", []) or []:
            for m in _attr(node, "cpeMatch", []) or []:
                item = {
                    "criteria": _attr(m, "criteria"),
                    "vulnerable": _attr(m, "vulnerable"),
                    "matchCriteriaId": _attr(m, "matchCriteriaId"),
                }
                out.append({k: v for k, v in item.items() if v is not None})
    return out or None


def _cwe_ids(cve: Any) -> list[str] | None:
    out: list[str] = []
    for w in _attr(cve, "weaknesses", []) or []:
        for d in _attr(w, "description", []) or []:
            val = _attr(d, "value")
            if val and val.startswith("CWE-"):
                out.append(val)
    return out or None


def extract_attack_techniques(cve: Any) -> list[tuple[str, str]]:
    """..: URL regex + tag-with-Exploit/VDB fallback. Returns
 deduplicated list of (technique_id, evidence_url) pairs, order-preserved
 relative to the references list.
"""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for ref in _attr(cve, "references", []) or []:
        url = _attr(ref, "url", "") or ""
        tags = set(_attr(ref, "tags", []) or [])
        # URL match first — highest-confidence signal.
        m = _ATTACK_URL_PATTERN.search(url)
        if m:
            tid = m.group(1).upper()
            if tid not in seen:
                out.append((tid, url))
                seen.add(tid)
            continue
        # Tag-based: T#### in tags alongside an Exploit or VDB Entry tag.
        if tags & _EXPLOIT_TAGS:
            for tag in tags:
                if _ATTACK_TAG_PATTERN.match(tag):
                    if tag not in seen:
                        out.append((tag, url))
                        seen.add(tag)
    return out


def normalise_cve(cve: Any, source_id: uuid.UUID) -> tuple[dict, dict, list[tuple[str, str]]] | None:
    """Normalise one nvdlib CVE object into (event_row, cve_details_row, attack_links).

 Returns None when the CVE is unhashable (missing id or lastModified).
"""
    cve_id = _attr(cve, "id")
    last_modified_str = _attr(cve, "lastModified")
    if not cve_id or not last_modified_str:
        return None

    observed_at = _parse_iso(_attr(cve, "published")) or _parse_iso(last_modified_str) \
        or datetime.now(timezone.utc)
    last_modified_dt = _parse_iso(last_modified_str)

    score, vector = _cvss_v3(cve)

    event_row = {
        "stix_type": _STIX_TYPE,
        "source_id": source_id,
        "raw_reference": cve_id,
        "observed_at": observed_at,
        "title": cve_id,
        "description": _first_english_description(cve),
        "content_hash": nvd_content_hash(str(source_id), cve_id, last_modified_str),
        "visibility": "shared",
    }
    cve_details_row = {
        "cve_id": cve_id,
        "cvss_v3_score": score,
        "cvss_v3_vector": vector,
        "cpe_match": _cpe_match(cve),
        "cwe_ids": _cwe_ids(cve),
        "last_modified": last_modified_dt,
    }
    attack_links = extract_attack_techniques(cve)
    return event_row, cve_details_row, attack_links
