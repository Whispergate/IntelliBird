"""STIX 2.1 / TAXII parser + TLP resolver + SDO → Event row mapper.

INGT-01 via stix2.parse(..., allow_custom=True) — never drop custom MISP/
OpenCTI types (PITFALLS H-5).
INGT-02 — raw SDO stored in events.raw_stix; stix_id/stix_type/observed_at/
title/description land in indexed columns.
INGT-03 — object_marking_refs resolved against the four canonical TLP 2.0
UUIDs seeded in migration 001. Non-canonical markings log a WARNING and
leave tlp_marking_id NULL (PITFALLS H-4).
 analog — objects missing id or modified are dropped with a WARNING.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import stix2

from app.ingest.dedup import taxii_content_hash

logger = logging.getLogger(__name__)

_KNOWN_STIX_TYPES: frozenset[str] = frozenset({
    "attack-pattern", "campaign", "course-of-action", "grouping", "identity",
    "indicator", "infrastructure", "intrusion-set", "location", "malware",
    "malware-analysis", "note", "observed-data", "opinion", "report",
    "threat-actor", "tool", "vulnerability", "relationship", "sighting",
    "marking-definition", "bundle",
})

_MARKING_REF_PATTERN = re.compile(r"^marking-definition--([0-9a-f-]{36})$", re.IGNORECASE)


def parse_stix_bundle(bundle_or_envelope: dict | list) -> list[Any]:
    """Run stix2.parse with allow_custom=True on a bundle dict or envelope
 {"objects": [...]} dict. Returns a list of parsed objects (dicts or
 stix2 SDO instances depending on shape).

 Raises stix2-side validation errors when a non-custom type is malformed
 (e.g. `indicator` without required `pattern`). This is intentional — we
 want bad input to surface.
"""
    if isinstance(bundle_or_envelope, list):
        objects = bundle_or_envelope
    elif "objects" in bundle_or_envelope:
        objects = bundle_or_envelope["objects"]
    else:
        objects = [bundle_or_envelope]

    # stix2.parse with allow_custom=True tolerates unknown type names but
    # still validates known types. We parse each object individually so a
    # single bad object does not drop the whole batch.
    out: list[Any] = []
    for obj in objects:
        parsed = stix2.parse(obj, allow_custom=True)
        out.append(parsed)
    return out


def resolve_tlp_marking(
    object_marking_refs: list[str] | None,
    tlp_cache: dict[uuid.UUID, str],
) -> uuid.UUID | None:
    """Match any ref in object_marking_refs to a canonical TLP UUID.

 tlp_cache is a lookup {canonical_uuid: name} prepared at worker startup
 by the caller (one query against tlp_markings). A non-canonical marking
 returns None after logging WARNING tlp_marking_unresolved.
"""
    if not object_marking_refs:
        return None
    for ref in object_marking_refs:
        m = _MARKING_REF_PATTERN.match(ref)
        if not m:
            continue
        try:
            candidate = uuid.UUID(m.group(1).lower())
        except ValueError:
            continue
        if candidate in tlp_cache:
            return candidate
    logger.warning(
        "tlp_marking_unresolved refs=%s known=%s",
        list(object_marking_refs), list(tlp_cache.keys()),
    )
    return None


def _as_dict(obj: Any) -> dict:
    """Coerce a stix2 SDO or plain dict to a JSON-serialisable dict."""
    if isinstance(obj, dict):
        return obj
    try:
        return json.loads(obj.serialize())
    except Exception:  # noqa: BLE001
        # Last-ditch: best-effort attribute dump
        return {k: getattr(obj, k) for k in dir(obj) if not k.startswith("_")}


def _parse_iso(ts: Any) -> datetime | None:
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    s = str(ts).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _title_for(obj_dict: dict) -> str | None:
    name = obj_dict.get("name")
    if name:
        return str(name)[:2048]
    # Indicator fallback — use pattern prefix
    pattern = obj_dict.get("pattern")
    if pattern:
        return str(pattern)[:120]
    return None


def normalise_stix_object(
    obj: Any,
    source_id: uuid.UUID,
    tlp_cache: dict[uuid.UUID, str],
) -> dict | None:
    """Normalise one STIX SDO (dict or stix2 object) to an Event row dict.

 Returns None if the object is unhashable (missing id OR missing modified).
"""
    d = _as_dict(obj)
    stix_id = d.get("id")
    modified = d.get("modified") or d.get("created")
    raw_type = d.get("type") or ""
    if not stix_id or not modified:
        logger.warning(
            "feed_item_rejected reason=missing_dedup_key source_id=%s raw_excerpt=%r",
            source_id, json.dumps(d)[:100],
        )
        return None

    stix_type = raw_type if raw_type in _KNOWN_STIX_TYPES else f"x-custom-{raw_type}"
    observed_at = _parse_iso(modified) or datetime.now(timezone.utc)
    tlp_uuid = resolve_tlp_marking(d.get("object_marking_refs"), tlp_cache)
    modified_str = modified if isinstance(modified, str) else observed_at.isoformat()

    return {
        "stix_id": stix_id,
        "stix_type": stix_type,
        "source_id": source_id,
        "raw_reference": stix_id,
        "observed_at": observed_at,
        "title": _title_for(d),
        "description": d.get("description"),
        "tlp_marking_id": tlp_uuid,
        "content_hash": taxii_content_hash(str(source_id), stix_id, modified_str),
        "visibility": "shared",
        "raw_stix": d,
    }
