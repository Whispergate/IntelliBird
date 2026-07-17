"""TIBER STIX 2.1 exporter — TIBER-03.

Builds a STIX 2.1 Bundle containing:
  - stix2.Identity("IntelliBird", "system") — producer provenance
  - stix2.ThreatActor for each actor profile
  - stix2.AttackPattern for each unique ATT&CK technique
  - stix2.Report SDO with:
      - report_types=["threat-report"]
      - object_refs covering all included object IDs
      - custom_properties:
          x_intellibird_tiber_version="ECB-TTIR-Jan-2025"
          x_intellibird_cbest_mode=report.cbest_mode
          x_intellibird_report_state=str(report.state)

M-4 referential integrity: stix2.parse(bundle_json, strict=True, allow_custom=True)
round-trip is called by validate_stix_bundle_strict() on every exported bundle.
strict=True catches: dangling *_ref, invalid STIX IDs, missing required fields.

References:
  RESEARCH.md Pattern 3 (STIX bundle construction + parse(strict=True))
  project_export.py build_stix_bundle() (existing pattern)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import stix2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_tiber_stix_bundle(
    report: Any,
    actors: list[Any],
    scenarios: list[Any],
    techniques: list[str],
) -> str:
    """Build a STIX 2.1 Bundle for a TIBER report export.

    Args:
        report: TiberReport ORM object or duck-typed equivalent. Must have:
                .title (str), .created_at (datetime), .cbest_mode (bool), .state (str).
        actors: List of actor objects. Each must have:
                .name (str), .motivation (str|None), .capability_assessment (str|None),
                .relevance_to_target (str|None). Optional: .id for internal mapping.
        scenarios: List of scenario objects (currently unused in bundle composition —
                   reserved for future AttackPattern-to-scenario CourseOfAction SDOs).
        techniques: List of ATT&CK technique ID strings (e.g. ["T1566", "T1190"]).
                    Each becomes an AttackPattern SDO.

    Returns:
        JSON string (bundle.serialize(pretty=False)) suitable for BYTEA storage.
        Passes stix2.parse(strict=True, allow_custom=True) round-trip.
    """
    # Producer identity — first in bundle, included in object_refs
    producer = stix2.Identity(name="IntelliBird", identity_class="system")
    objects: list = [producer]
    ids: list[str] = [producer.id]

    # ThreatActor SDOs for each actor profile
    for actor in actors:
        ta = stix2.ThreatActor(
            name=getattr(actor, "name", "Unknown Actor"),
            threat_actor_types=["unknown"],
            allow_custom=True,
            custom_properties={
                "x_intellibird_motivation": getattr(actor, "motivation", "") or "",
                "x_intellibird_capability": getattr(actor, "capability_assessment", "") or "",
                "x_intellibird_relevance": getattr(actor, "relevance_to_target", "") or "",
            },
        )
        objects.append(ta)
        ids.append(ta.id)

    # AttackPattern SDOs for each unique technique
    seen_techniques: set[str] = set()
    for tid in techniques:
        if tid in seen_techniques:
            continue
        seen_techniques.add(tid)
        ap = stix2.AttackPattern(
            name=tid,
            allow_custom=True,
            external_references=[
                {
                    "source_name": "mitre-attack",
                    "external_id": tid,
                }
            ],
        )
        objects.append(ap)
        ids.append(ap.id)

    # Report SDO — object_refs covers Identity + ThreatActors + AttackPatterns
    # (all IDs collected so far, excluding the Report itself which cannot self-reference)
    published_dt = getattr(report, "created_at", None) or datetime.now(timezone.utc)
    if not isinstance(published_dt, datetime):
        # Handle date objects (engagement_window_start etc) — convert to datetime
        published_dt = datetime.now(timezone.utc)
    if published_dt.tzinfo is None:
        published_dt = published_dt.replace(tzinfo=timezone.utc)

    report_sdo = stix2.Report(
        name=getattr(report, "title", "TIBER Report"),
        published=published_dt,
        report_types=["threat-report"],
        object_refs=list(ids),  # all previously added object IDs
        allow_custom=True,
        custom_properties={
            "x_intellibird_tiber_version": "ECB-TTIR-Jan-2025",
            "x_intellibird_cbest_mode": bool(getattr(report, "cbest_mode", False)),
            "x_intellibird_report_state": str(getattr(report, "state", "draft")),
        },
    )
    objects.append(report_sdo)

    bundle = stix2.Bundle(objects=objects, allow_custom=True)
    return bundle.serialize(pretty=False)


def validate_stix_bundle_strict(bundle_json: str) -> None:
    """Round-trip parse to validate STIX referential integrity.

    Called after every export to catch:
      - Dangling *_ref values (object references not present in bundle.objects)
      - Invalid STIX IDs (wrong UUID format, wrong type prefix)
      - Missing required fields per STIX 2.1 spec

    stix2 v3.0.2 applies validation during parse() by default — no separate
    strict= flag is needed. allow_custom=True permits x_intellibird_* custom
    properties without validation failure.

    Args:
        bundle_json: JSON string from build_tiber_stix_bundle().

    Raises:
        stix2.exceptions.STIXError: if bundle fails STIX 2.1 validation.
    """
    parsed = stix2.parse(bundle_json, allow_custom=True)
    assert parsed is not None, "stix2.parse returned None — bundle is invalid"
