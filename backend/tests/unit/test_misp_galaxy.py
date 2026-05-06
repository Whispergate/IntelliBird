"""
MISP-04 — MISP galaxy clusters of type 'threat-actor' map to threat_actors rows.
          Dedup on mitre_group_id first, then primary_name fallback.

Implemented in: backend/app/workers/misp_pull.py (Phase 32 Plan 04)
"""
import pytest


@pytest.mark.xfail(reason="galaxy mapping not yet implemented", strict=False)
def test_galaxy_dedup_on_mitre_group_id():
    """When mitre_group_id is present, existing actor with same ID is not duplicated."""
    from app.workers.misp_pull import _should_insert_actor
    existing = {"mitre_group_id": "G0016", "primary_name": "APT29"}
    cluster = {"mitre_group_id": "G0016", "primary_name": "Cozy Bear"}
    assert _should_insert_actor(cluster, [existing]) is False


@pytest.mark.xfail(reason="galaxy mapping not yet implemented", strict=False)
def test_galaxy_dedup_null_mitre_falls_back_to_name():
    """When mitre_group_id is NULL, fall back to exact primary_name match."""
    from app.workers.misp_pull import _should_insert_actor
    existing = {"mitre_group_id": None, "primary_name": "LazarusGroup"}
    cluster = {"mitre_group_id": None, "primary_name": "LazarusGroup"}
    assert _should_insert_actor(cluster, [existing]) is False


@pytest.mark.xfail(reason="galaxy mapping not yet implemented", strict=False)
def test_galaxy_new_actor_inserted():
    """Unknown actor (no mitre_group_id match, no name match) returns True."""
    from app.workers.misp_pull import _should_insert_actor
    existing = [{"mitre_group_id": "G0016", "primary_name": "APT29"}]
    cluster = {"mitre_group_id": "G0099", "primary_name": "NewActor"}
    assert _should_insert_actor(cluster, existing) is True


@pytest.mark.xfail(reason="galaxy mapping not yet implemented", strict=False)
def test_galaxy_multiple_null_mitre_ids_not_collapsed():
    """Multiple actors with NULL mitre_group_id are deduplicated only by primary_name."""
    from app.workers.misp_pull import _should_insert_actor
    existing = [{"mitre_group_id": None, "primary_name": "ActorA"}]
    cluster = {"mitre_group_id": None, "primary_name": "ActorB"}
    assert _should_insert_actor(cluster, existing) is True
