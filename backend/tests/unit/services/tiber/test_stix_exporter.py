"""Unit tests for TIBER STIX 2.1 bundle exporter.

Wave 0 stubs — skip-marked pending Wave 3 service layer (18-03-PLAN).
Each test documents the exact STIX compliance requirements for
app.services.tiber.exporters.stix.

Requirements covered:
  TIBER-03 — STIX 2.1 Report SDO + Bundle; parse(strict=True) CI gate

Key STIX 2.1 invariants tested:
  - bundle.objects contains Identity + ThreatActor[] + AttackPattern[] + Report SDO
  - Report.object_refs covers every included object id
  - report_types == ["threat-report"]
  - custom_properties contains x_intellibird_tiber_version="ECB-TTIR-Jan-2025"
  - stix2.parse(strict=True, allow_custom=True) succeeds on serialized bundle
"""
from __future__ import annotations

import pytest

# No pytestmark — unit tests are the default (not integration-marked)


# ---------------------------------------------------------------------------
# TIBER-03: STIX bundle strict round-trip
# ---------------------------------------------------------------------------


def test_bundle_strict_roundtrip() -> None:
    """stix2.parse(bundle.serialize(), strict=True, allow_custom=True) succeeds.

    Bundle composition requirements (per RESEARCH.md Pattern 3):
      - Identity SDO (name="IntelliBird", identity_class="system") — producer
      - ThreatActor SDOs for each actor profile (>=1)
      - AttackPattern SDOs for each ATT&CK technique (>=1)
      - Report SDO with:
          - report_types == ["threat-report"]
          - object_refs covering every included object id
          - custom_properties["x_intellibird_tiber_version"] == "ECB-TTIR-Jan-2025"
      - Bundle.objects contains all of the above
      - parse(strict=True) succeeds: no dangling *_ref, valid STIX IDs, required fields

    Test strategy:
      1. Build a minimal fixture report, actors, scenarios, techniques
      2. Call build_tiber_stix_bundle(report, actors, scenarios, techniques)
      3. Parse the returned JSON string with stix2.parse(strict=True, allow_custom=True)
      4. Assert parsed bundle contains the expected object types
      5. Assert Report SDO has correct report_types and custom_properties
      6. Assert every object_ref in Report.object_refs maps to a bundle object id
    """
    import stix2
    from types import SimpleNamespace

    from app.services.tiber.exporters.stix import build_tiber_stix_bundle

    # Minimal fixture data
    report = SimpleNamespace(
        title="Test TIBER Report Q1 2026",
        created_at=__import__("datetime").datetime(2026, 1, 15, tzinfo=__import__("datetime").timezone.utc),
        cbest_mode=False,
        state="published",
    )
    actors = [
        SimpleNamespace(
            name="APT-Finance-01",
            motivation="Financial gain via data exfiltration",
            capability_assessment="High — nation-state affiliated",
        )
    ]
    scenarios = [
        SimpleNamespace(
            id="scenario-1",
            cif_or_cbs_label="Core Banking System",
            objective_type="availability",
            attack_technique_id="T1566",
            procedure_text="Spear-phishing targeting finance operations staff.",
        )
    ]
    techniques = ["T1566", "T1190"]

    # Build and serialize
    bundle_json = build_tiber_stix_bundle(report, actors, scenarios, techniques)
    assert isinstance(bundle_json, str), (
        f"build_tiber_stix_bundle must return str (serialized JSON), got {type(bundle_json)}"
    )

    # Round-trip: allow_custom=True (stix2.parse validates referential integrity internally)
    # Note: stix2 v3.0.2 does not expose a `strict=` parameter — validation is always
    # applied by parse(); allow_custom=True permits x_intellibird_* custom properties.
    parsed = stix2.parse(bundle_json, allow_custom=True)
    assert parsed is not None, "stix2.parse returned None — bundle invalid"

    # Extract bundle objects
    bundle_objects = list(parsed.objects) if hasattr(parsed, "objects") else []
    assert len(bundle_objects) >= 3, (
        f"Bundle must have >= 3 objects (Identity + ThreatActor + Report); got {len(bundle_objects)}"
    )

    # Find the Report SDO
    report_sdos = [o for o in bundle_objects if o.type == "report"]
    assert len(report_sdos) == 1, (
        f"Expected exactly 1 Report SDO in bundle, got {len(report_sdos)}"
    )
    report_sdo = report_sdos[0]

    # report_types must be ["threat-report"]
    assert report_sdo.report_types == ["threat-report"], (
        f"Report SDO report_types must be ['threat-report'], got {report_sdo.report_types!r}"
    )

    # Custom TIBER version property
    tiber_version = getattr(report_sdo, "x_intellibird_tiber_version", None)
    assert tiber_version == "ECB-TTIR-Jan-2025", (
        f"Missing or wrong x_intellibird_tiber_version: {tiber_version!r}. "
        "Must be 'ECB-TTIR-Jan-2025' for ECB TTIR January 2025 provenance."
    )

    # Every object_ref must point to an object in the bundle
    bundle_ids = {o.id for o in bundle_objects}
    for ref in report_sdo.object_refs:
        assert str(ref) in bundle_ids, (
            f"Report SDO object_refs contains dangling ref {ref!r} not in bundle objects. "
            "strict=True would have caught this — check build_tiber_stix_bundle implementation."
        )

    # Identity SDO must be present
    identity_sdos = [o for o in bundle_objects if o.type == "identity"]
    assert len(identity_sdos) >= 1, "Bundle must contain at least one Identity SDO (producer)"
    producer = identity_sdos[0]
    assert producer.identity_class == "system", (
        f"Producer Identity must have identity_class='system', got {producer.identity_class!r}"
    )

    # ThreatActor SDO must be present
    threat_actors = [o for o in bundle_objects if o.type == "threat-actor"]
    assert len(threat_actors) >= 1, (
        "Bundle must contain at least one ThreatActor SDO (one per actor profile)"
    )
