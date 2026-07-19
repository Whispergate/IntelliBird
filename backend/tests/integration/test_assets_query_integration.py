"""Integration tests for build_assets_aggregation_select against a live DB.

Plan 12.1-03 / Task 3 behaviour 9.
"""
from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import text

from app.services.assets_query import build_assets_aggregation_select

pytestmark = pytest.mark.integration


def _content_hash(project_id: uuid.UUID, bbot_event_type: str, canonical_target: str) -> str:
    raw = f"{project_id}{bbot_event_type}{canonical_target}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


async def _seed_project(db_session, project_id: uuid.UUID) -> None:
    await db_session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (CAST(:id AS uuid), :name, 'red_team', :created_by, false)"
        ),
        {"id": str(project_id), "name": f"test-proj-{project_id}", "created_by": "tester"},
    )


async def _seed_scan(db_session, scan_id: uuid.UUID, project_id: uuid.UUID) -> None:
    await db_session.execute(
        text(
            "INSERT INTO easm_scans (id, project_id, status, scan_mode, modules, started_at, launched_by) "
            "VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), 'finished'::easm_scan_status, "
            "'passive'::easm_scan_mode, ARRAY['crt'], now(), :by)"
        ),
        {"id": str(scan_id), "pid": str(project_id), "by": "tester"},
    )


async def _seed_finding(
    db_session,
    project_id: uuid.UUID,
    scan_id: uuid.UUID,
    bbot_event_type: str,
    canonical_target: str,
    module: str = "crt",
) -> None:
    await db_session.execute(
        text(
            "INSERT INTO easm_findings "
            "(id, project_id, scan_id, bbot_event_type, canonical_target, module, raw_bbot, "
            " content_hash, first_seen, last_seen, lifecycle_status) "
            "VALUES (gen_random_uuid(), CAST(:pid AS uuid), CAST(:sid AS uuid), :bet, :ct, :mod, "
            " '{}'::jsonb, :ch, now(), now(), 'new'::easm_lifecycle)"
        ),
        {
            "pid": str(project_id),
            "sid": str(scan_id),
            "bet": bbot_event_type,
            "ct": canonical_target,
            "mod": module,
            "ch": _content_hash(project_id, bbot_event_type, canonical_target),
        },
    )


@pytest.mark.asyncio
async def test_aggregation_deduplicates_by_type_and_target(db_session):
    """Seeding 3 rows (2 sharing (type, target), 1 different) returns 2 aggregated rows
    with scan_count = count(distinct scan_id)."""
    project_id = uuid.uuid4()
    scan_a = uuid.uuid4()
    scan_b = uuid.uuid4()

    await _seed_project(db_session, project_id)
    await _seed_scan(db_session, scan_a, project_id)
    await _seed_scan(db_session, scan_b, project_id)

    # Two rows matching (DNS_NAME, api.example.com) across two scans - but UNIQUE
    # constraint dedups on (project_id, bbot_event_type, canonical_target). Insert
    # once, then a different type/target, then a different target to produce two
    # aggregation groups.
    await _seed_finding(
        db_session, project_id, scan_a, "DNS_NAME", "api.example.com"
    )
    await _seed_finding(
        db_session, project_id, scan_a, "DNS_NAME", "other.example.com"
    )
    await db_session.commit()

    stmt = build_assets_aggregation_select(project_id)
    result = await db_session.execute(stmt)
    rows = result.all()

    # Expect 2 aggregated rows (two distinct canonical_targets)
    assert len(rows) == 2
    targets = {r.canonical_target for r in rows}
    assert targets == {"api.example.com", "other.example.com"}
    for r in rows:
        assert r.bbot_event_type == "DNS_NAME"
        assert r.scan_count == 1
        assert r.modules == ["crt"]
