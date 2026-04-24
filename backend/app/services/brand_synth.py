"""Brand match → canonical event + STIX 2.1 Indicator SDO construction.

Phase 12 / BRP-05.

HIGH-severity brand matches are synthesised into canonical events written to the
`events` table (observed_at + content_hash dedup pattern reused from Phase 2).
This module is pure: it constructs the dict; persistence is orchestrator-owned.

STIX 2.1 Indicator SDO is emitted with `allow_custom=True` so x_intellibird_*
custom properties (match_id / project_id / term_id) ride along with the
canonical stix2 object. Pattern branching:

  term_type='domain'           → [domain-name:value = '<matched>']
  term_type in {keyword, product, person}
                               → [x_intellibird_brand_match_keyword:value = '<matched>']

content_hash formula (locked):
  sha256(str(project_id) + 'brand-match' + str(brand_term_id) + matched_value)
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import stix2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _content_hash(
    project_id: UUID | str,
    brand_term_id: UUID | str,
    matched_value: str,
) -> str:
    """Deterministic sha256 hex digest used for events-table dedup."""
    raw = f"{project_id}brand-match{brand_term_id}{matched_value}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _stix_pattern(term_type: str, matched_value: str) -> str:
    """STIX 2.1 pattern for a brand match.

    Domain terms map to the canonical SCO `domain-name:value`; keyword /
    product / person fall back to the custom x_intellibird namespace (there
    is no standard SCO for arbitrary brand strings).
    """
    if term_type == "domain":
        return f"[domain-name:value = '{matched_value}']"
    return f"[x_intellibird_brand_match_keyword:value = '{matched_value}']"


# ---------------------------------------------------------------------------
# STIX 2.1 Indicator SDO
# ---------------------------------------------------------------------------

def build_stix_indicator(
    *,
    match_id: UUID | str,
    project_id: UUID | str,
    term_id: UUID | str,
    term_type: str,
    term_value: str,
    matched_value: str,
    severity: str,
) -> dict[str, Any]:
    """Return a serialised STIX 2.1 Indicator dict with x_intellibird_* custom props."""
    indicator = stix2.Indicator(
        name=f"Brand match: {term_value} ({severity})",
        pattern=_stix_pattern(term_type, matched_value),
        pattern_type="stix",
        labels=[
            "brand-match",
            f"brand-match:{severity}",
            f"project:{project_id}",
        ],
        custom_properties={
            "x_intellibird_brand_match_id": str(match_id),
            "x_intellibird_project_id": str(project_id),
            "x_intellibird_term_id": str(term_id),
        },
        allow_custom=True,
    )
    return json.loads(indicator.serialize())


# ---------------------------------------------------------------------------
# Canonical event dict
# ---------------------------------------------------------------------------

def build_event_dict(
    *,
    match: dict[str, Any],
    term: dict[str, Any],
) -> dict[str, Any]:
    """Build the canonical events-table row dict for a HIGH-severity brand match.

    ``match`` shape (from brand_matches row):
        id, project_id, brand_term_id, matched_value, match_source, severity,
        first_seen
    ``term`` shape (from brand_terms row):
        id, value, term_type
    """
    project_id = match["project_id"]
    matched_value = match["matched_value"]
    match_source = match["match_source"]
    severity = match["severity"]
    first_seen = match["first_seen"]
    first_seen_iso = (
        first_seen.isoformat()
        if hasattr(first_seen, "isoformat")
        else str(first_seen)
    )

    raw_stix = build_stix_indicator(
        match_id=match["id"],
        project_id=project_id,
        term_id=term["id"],
        term_type=term["term_type"],
        term_value=term["value"],
        matched_value=matched_value,
        severity=severity,
    )

    description = (
        f"Matched value: {matched_value}\n"
        f"Source: {match_source}\n"
        f"Term type: {term['term_type']}\n"
        f"First seen: {first_seen_iso}\n"
        f"Dashboard: /projects/{project_id}/brand"
    )

    return {
        "stix_type": "indicator",
        "stix_id": raw_stix.get("id"),
        "title": f"Brand match: {term['value']} ({severity})",
        "description": description,
        "observed_at": datetime.now(timezone.utc),
        "tags": [
            "brand-match",
            f"brand-match:{severity}",
            f"brand-match:{match_source}",
            f"project:{project_id}",
        ],
        "raw_stix": raw_stix,
        "content_hash": _content_hash(project_id, term["id"], matched_value),
        "project_id": project_id,
    }
