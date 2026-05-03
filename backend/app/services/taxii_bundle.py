"""TAXII bundle builder — Phase 26 / TAXII-02, TAXII-04.

Converts Event ORM rows to STIX 2.1 SDO dicts for outbound TAXII responses.
TLP filtering happens at the SQL predicate layer (build_tlp_predicate), not here.

Key design decisions (RESEARCH.md §Pattern 6):
  - Events with valid raw_stix are returned as-is (passthrough).
  - Events without raw_stix are wrapped as stix2.ObservedData with x_intellibird_*
    custom properties. We do NOT build a proper SCO graph for RSS events — too expensive.
  - Do NOT wrap objects in stix2.Bundle on the objects endpoint — TAXII spec §5.4
    says the objects endpoint envelope contains raw SDOs, not a bundle.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import stix2
import structlog
from sqlalchemy import ColumnElement, select

from app.models.events import Event
from app.models.markings import TlpMarking

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# TLP level ordering — RESEARCH.md §Pattern 5
# ---------------------------------------------------------------------------

TLP_LEVELS: dict[str, int] = {
    "white": 0,
    "clear": 0,
    "green": 1,
    "amber": 2,
    "amber+strict": 3,
    "red": 4,
}


def build_tlp_predicate(max_level: str) -> ColumnElement:
    """Build a SQLAlchemy WHERE predicate that allows only TLP levels <= max_level.

    Args:
        max_level: One of 'white', 'clear', 'green', 'amber', 'amber+strict', 'red'.

    Returns:
        A SQLAlchemy column expression suitable for use in .where().
    """
    cap = TLP_LEVELS.get(max_level.lower(), 1)  # default to green cap if unknown
    allowed = [name for name, rank in TLP_LEVELS.items() if rank <= cap]
    return Event.tlp_marking_id.in_(
        select(TlpMarking.id).where(TlpMarking.name.in_(allowed)).scalar_subquery()
    )


# ---------------------------------------------------------------------------
# Event -> STIX SDO converter
# ---------------------------------------------------------------------------

def event_to_stix_sdo(event: Event, tlp_cache: dict[str, Any]) -> dict:
    """Convert an Event ORM row to a STIX 2.1 SDO dict.

    Priority order:
      1. If event.raw_stix is a dict/str and event.stix_type is a known SDO type -> passthrough.
      2. Otherwise -> wrap as stix2.ObservedData with x_intellibird_* custom properties.

    Args:
        event: Event ORM row (must have id, title, observed_at, raw_stix, stix_type, project_id).
        tlp_cache: Unused; reserved for future TLP object embedding.

    Returns:
        A dict that is a valid STIX 2.1 SDO (serialisable to JSON).
    """
    _PASSTHROUGH_TYPES = frozenset({"indicator", "observed-data", "vulnerability", "report"})

    # Passthrough path: event already has valid STIX SDO stored
    if event.raw_stix and event.stix_type in _PASSTHROUGH_TYPES:
        if isinstance(event.raw_stix, dict):
            return event.raw_stix
        # raw_stix might be a JSON string in some older rows
        try:
            return json.loads(event.raw_stix)
        except (TypeError, ValueError):
            pass  # fall through to generic wrapper

    # Generic wrapper path: RSS, NVD CVEs without structured STIX, dark-web events
    now = datetime.now(timezone.utc)
    observed_at = event.observed_at or now

    try:
        sdo = stix2.ObservedData(
            first_observed=observed_at,
            last_observed=observed_at,
            number_observed=1,
            object_refs=["x-intellibird-event--" + str(event.id)],
            allow_custom=True,
            custom_properties={
                "x_intellibird_title": event.title or "",
                "x_intellibird_source_id": str(event.source_id) if event.source_id else None,
                "x_intellibird_project_id": str(event.project_id),
                "x_intellibird_event_id": str(event.id),
            },
        )
        return json.loads(sdo.serialize())
    except Exception:
        log.exception("taxii_bundle.event_to_stix_sdo_failed", event_id=str(event.id))
        # Last-resort fallback: minimal valid dict
        return {
            "type": "observed-data",
            "spec_version": "2.1",
            "id": f"observed-data--{uuid.uuid4()}",
            "created": now.isoformat(),
            "modified": now.isoformat(),
            "first_observed": observed_at.isoformat(),
            "last_observed": observed_at.isoformat(),
            "number_observed": 1,
            "object_refs": [],
            "x_intellibird_title": event.title or "",
            "x_intellibird_event_id": str(event.id),
        }


__all__ = ["event_to_stix_sdo", "build_tlp_predicate", "TLP_LEVELS"]
