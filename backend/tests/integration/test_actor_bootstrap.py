"""Integration test stubs — MITRE ATT&CK actor bootstrap ingest.

Phase 25 Wave 0: all tests are xfail stubs. They will go GREEN when
plan 25-03 ships the bootstrap_attack() service and threat_actors table.

Coverage:
  ACTOR-02 — bootstrap ingests ATT&CK intrusion sets into threat_actors;
             upsert preserves analyst profile_md notes; aliases populated.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.xfail(strict=False, reason="implementation pending — Phase 25 plan 25-03")
async def test_bootstrap_ingests_intrusion_sets():
    """After bootstrap_attack() runs, at least 100 threat_actors rows exist.

    The bundled enterprise-attack.json contains 187 intrusion-set objects.
    SELECT COUNT(*) FROM threat_actors must be >= 100 after a cold bootstrap.
    """
    assert False, "stub — implement after bootstrap service ships"


@pytest.mark.xfail(strict=False, reason="implementation pending — Phase 25 plan 25-03")
async def test_upsert_preserves_profile_md():
    """bootstrap_attack() does NOT overwrite existing profile_md analyst notes.

    Setup: INSERT a threat_actors row with primary_name matching a known ATT&CK
    group and profile_md = 'analyst note'. Run bootstrap_attack() again.
    Assert profile_md is UNCHANGED (upsert must NOT touch the analyst column).
    """
    assert False, "stub — implement after bootstrap service ships"


@pytest.mark.xfail(strict=False, reason="implementation pending — Phase 25 plan 25-03")
async def test_bootstrap_actor_has_aliases():
    """After bootstrap_attack(), at least one threat_actors row has len(aliases) > 0.

    ATT&CK intrusion sets include aliases (x_mitre_aliases field in STIX).
    The array must be populated on the row, not discarded during ingest.
    """
    assert False, "stub — implement after bootstrap service ships"
