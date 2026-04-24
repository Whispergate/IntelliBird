"""Integration tests — easm_promoter: events.easm_scan_id ON DELETE SET NULL survival (L-4).

Plan 11-03 / EASM-06 / L-4.

Tests require:
- testcontainer PostgreSQL running intellibird-db:m1 image (has TimescaleDB + AGE + all migrations)
- db_session fixture from conftest.py (runs alembic upgrade head)

L-4 regression: when an easm_scan is deleted, promoted events must survive with
easm_scan_id=NULL rather than being cascade-deleted.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# In-memory stubs — same shape as in unit tests
# ---------------------------------------------------------------------------

@dataclass
class _F:
    """Minimal stub matching EASMFinding attributes consumed by the promoter."""
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    project_id: uuid.UUID = field(default_factory=uuid.uuid4)
    bbot_event_type: str = "VULNERABILITY"
    canonical_target: str = "sub.example.com"
    severity: str | None = None
    module: str = "nuclei"
    raw_bbot: dict = field(default_factory=lambda: {
        "data": {"description": "SQL injection on /login", "severity": None, "url": "https://sub.example.com/login"}
    })
    content_hash: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class _S:
    """Minimal stub matching EASMScan attributes consumed by the promoter."""
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    project_id: uuid.UUID = field(default_factory=uuid.uuid4)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event_row(kwargs: dict[str, Any], project_id: uuid.UUID, scan_id: uuid.UUID) -> dict[str, Any]:
    """Strip non-ORM keys from promote_finding_to_event result and fill required fields."""
    row = dict(kwargs)
    # source_type is documentation metadata in the dict but not an ORM column
    row.pop("source_type", None)
    # summary is not an Event ORM column either — it maps to 'description'
    description = row.pop("summary", None)
    row["description"] = description
    # Ensure project_id is correct UUID (promoter returns finding.project_id which is already set)
    row["project_id"] = project_id
    # easm_scan_id comes from the kwargs
    return row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_promote_finding_writes_event_with_easm_scan_id(db_session):
    """Promoted VULNERABILITY finding inserts an events row with easm_scan_id set."""
    from app.services.easm_promoter import promote_finding_to_event
    from sqlalchemy import text

    project_id = uuid.UUID("00000000-0000-0000-0000-000000000001")  # LEGACY_PROJECT_ID sentinel

    # Create an easm_scan row directly via SQL
    scan_id = uuid.uuid4()
    await db_session.execute(text("""
        INSERT INTO easm_scans (id, project_id, status, scan_mode, modules, started_at, launched_by)
        VALUES (
            CAST(:scan_id AS uuid),
            CAST(:project_id AS uuid),
            'finished'::easm_scan_status,
            'passive'::easm_scan_mode,
            ARRAY['certspotter'],
            now(),
            'test-user-sub'
        )
    """), {"scan_id": str(scan_id), "project_id": str(project_id)})
    await db_session.commit()

    # Build a stub finding pointing at the scan + project
    finding = _F(project_id=project_id, bbot_event_type="VULNERABILITY")
    scan = _S(id=scan_id, project_id=project_id)

    kwargs = promote_finding_to_event(finding, scan)
    assert kwargs["source_type"] == "bbot"
    assert kwargs["easm_scan_id"] == scan_id

    # Insert the promoted event row
    row = _make_event_row(kwargs, project_id=project_id, scan_id=scan_id)
    stix_id = row["stix_id"]

    await db_session.execute(text("""
        INSERT INTO events (
            id, stix_id, stix_type, project_id, easm_scan_id,
            observed_at, content_hash, raw_stix, title
        ) VALUES (
            gen_random_uuid(),
            :stix_id,
            :stix_type,
            CAST(:project_id AS uuid),
            CAST(:easm_scan_id AS uuid),
            :observed_at,
            :content_hash,
            CAST(:raw_stix AS jsonb),
            :title
        )
    """), {
        "stix_id": stix_id,
        "stix_type": row["stix_type"],
        "project_id": str(project_id),
        "easm_scan_id": str(scan_id),
        "observed_at": row["observed_at"],
        "content_hash": row["content_hash"],
        "raw_stix": row["raw_stix"],
        "title": row["title"],
    })
    await db_session.commit()

    # Verify the row was inserted with easm_scan_id set
    result = await db_session.execute(text("""
        SELECT easm_scan_id::text FROM events WHERE stix_id = :stix_id
    """), {"stix_id": stix_id})
    row_result = result.fetchone()
    assert row_result is not None, "Event row was not inserted"
    assert row_result[0] == str(scan_id), f"easm_scan_id mismatch: {row_result[0]} != {scan_id}"


@pytest.mark.asyncio
async def test_scan_deletion_sets_events_easm_scan_id_null(db_session):
    """L-4 regression: deleting easm_scan sets events.easm_scan_id to NULL, not delete the event."""
    from app.services.easm_promoter import promote_finding_to_event

    project_id = uuid.UUID("00000000-0000-0000-0000-000000000001")  # LEGACY_PROJECT_ID

    # Setup: create a scan + finding + promoted event
    scan_id = uuid.uuid4()
    await db_session.execute(text("""
        INSERT INTO easm_scans (id, project_id, status, scan_mode, modules, started_at, launched_by)
        VALUES (
            CAST(:scan_id AS uuid),
            CAST(:project_id AS uuid),
            'finished'::easm_scan_status,
            'passive'::easm_scan_mode,
            ARRAY['certspotter'],
            now(),
            'test-user-sub'
        )
    """), {"scan_id": str(scan_id), "project_id": str(project_id)})
    await db_session.commit()

    finding = _F(project_id=project_id, bbot_event_type="VULNERABILITY",
                 content_hash=uuid.uuid4().hex)
    scan = _S(id=scan_id, project_id=project_id)
    kwargs = promote_finding_to_event(finding, scan)
    stix_id = kwargs["stix_id"]

    await db_session.execute(text("""
        INSERT INTO events (
            id, stix_id, stix_type, project_id, easm_scan_id,
            observed_at, content_hash, raw_stix, title
        ) VALUES (
            gen_random_uuid(),
            :stix_id,
            :stix_type,
            CAST(:project_id AS uuid),
            CAST(:easm_scan_id AS uuid),
            :observed_at,
            :content_hash,
            CAST(:raw_stix AS jsonb),
            :title
        )
    """), {
        "stix_id": stix_id,
        "stix_type": kwargs["stix_type"],
        "project_id": str(project_id),
        "easm_scan_id": str(scan_id),
        "observed_at": kwargs["observed_at"],
        "content_hash": kwargs["content_hash"],
        "raw_stix": kwargs["raw_stix"],
        "title": kwargs["title"],
    })
    await db_session.commit()

    # Verify event exists with easm_scan_id set
    before_result = await db_session.execute(text("""
        SELECT easm_scan_id FROM events WHERE stix_id = :stix_id
    """), {"stix_id": stix_id})
    before_row = before_result.fetchone()
    assert before_row is not None, "Event row not found before scan deletion"
    assert before_row[0] == scan_id, f"Expected easm_scan_id={scan_id}, got {before_row[0]}"

    # L-4: Delete the scan — easm_findings CASCADE, but events SET NULL
    await db_session.execute(text("""
        DELETE FROM easm_scans WHERE id = CAST(:scan_id AS uuid)
    """), {"scan_id": str(scan_id)})
    await db_session.commit()

    # Verify: event still exists, easm_scan_id is now NULL
    after_result = await db_session.execute(text("""
        SELECT easm_scan_id FROM events WHERE stix_id = :stix_id
    """), {"stix_id": stix_id})
    after_row = after_result.fetchone()
    assert after_row is not None, "Event row was deleted when scan was deleted — L-4 violation"
    assert after_row[0] is None, (
        f"easm_scan_id should be NULL after scan deletion (L-4), but got {after_row[0]}"
    )


@pytest.mark.asyncio
async def test_dns_name_finding_not_promoted(db_session):
    """DNS_NAME findings must not be promoted — H-4 feed contamination prevention."""
    from app.services.easm_promoter import should_promote, promote_finding_to_event

    project_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

    # should_promote returns False
    assert should_promote("DNS_NAME", None) is False

    # promote_finding_to_event raises ValueError
    finding = _F(bbot_event_type="DNS_NAME", severity=None, raw_bbot={"data": "sub.example.com"})
    scan = _S(project_id=project_id)

    with pytest.raises(ValueError, match="not promotable"):
        promote_finding_to_event(finding, scan)

    # No event row should be inserted (ValueError prevented any insert attempt)
    result = await db_session.execute(text("""
        SELECT count(*) FROM events WHERE stix_type = 'dns-name'
    """))
    count = result.scalar()
    assert count == 0, f"Expected 0 dns-name events, found {count}"


@pytest.mark.asyncio
async def test_feed_exclusion_source_type_values(db_session):
    """Promoted BBOT events and regular feed events produce correct provenance signals.

    This test validates the DB side only: BBOT events have easm_scan_id set,
    RSS events have source_id set. The feed-exclusion filter (include_bbot=true)
    is tested in plan 11-05 router integration tests.
    """
    from app.services.easm_promoter import promote_finding_to_event

    project_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

    # Insert an RSS-style event (no easm_scan_id)
    rss_content_hash = uuid.uuid4().hex
    await db_session.execute(text("""
        INSERT INTO events (
            id, stix_id, stix_type, project_id, easm_scan_id,
            observed_at, content_hash, raw_stix, title
        ) VALUES (
            gen_random_uuid(),
            :stix_id,
            'indicator',
            CAST(:project_id AS uuid),
            NULL,
            now(),
            :content_hash,
            'null'::jsonb,
            'RSS event'
        )
    """), {
        "stix_id": f"indicator--{uuid.uuid4()}",
        "project_id": str(project_id),
        "content_hash": rss_content_hash,
    })

    # Create a scan + promoted BBOT event
    scan_id = uuid.uuid4()
    await db_session.execute(text("""
        INSERT INTO easm_scans (id, project_id, status, scan_mode, modules, started_at, launched_by)
        VALUES (
            CAST(:scan_id AS uuid),
            CAST(:project_id AS uuid),
            'finished'::easm_scan_status,
            'passive'::easm_scan_mode,
            ARRAY['certspotter'],
            now(),
            'test-user-sub'
        )
    """), {"scan_id": str(scan_id), "project_id": str(project_id)})

    finding = _F(project_id=project_id, bbot_event_type="VULNERABILITY",
                 content_hash=uuid.uuid4().hex)
    scan = _S(id=scan_id, project_id=project_id)
    kwargs = promote_finding_to_event(finding, scan)

    await db_session.execute(text("""
        INSERT INTO events (
            id, stix_id, stix_type, project_id, easm_scan_id,
            observed_at, content_hash, raw_stix, title
        ) VALUES (
            gen_random_uuid(),
            :stix_id,
            :stix_type,
            CAST(:project_id AS uuid),
            CAST(:easm_scan_id AS uuid),
            :observed_at,
            :content_hash,
            CAST(:raw_stix AS jsonb),
            :title
        )
    """), {
        "stix_id": kwargs["stix_id"],
        "stix_type": kwargs["stix_type"],
        "project_id": str(project_id),
        "easm_scan_id": str(scan_id),
        "observed_at": kwargs["observed_at"],
        "content_hash": kwargs["content_hash"],
        "raw_stix": kwargs["raw_stix"],
        "title": kwargs["title"],
    })
    await db_session.commit()

    # Events with easm_scan_id set = BBOT-promoted
    bbot_result = await db_session.execute(text("""
        SELECT count(*) FROM events WHERE easm_scan_id IS NOT NULL
    """))
    bbot_count = bbot_result.scalar()
    assert bbot_count >= 1, "Expected at least 1 BBOT-promoted event"

    # Events with easm_scan_id NULL = non-BBOT (RSS/NVD/TAXII)
    non_bbot_result = await db_session.execute(text("""
        SELECT count(*) FROM events WHERE easm_scan_id IS NULL
    """))
    non_bbot_count = non_bbot_result.scalar()
    assert non_bbot_count >= 1, "Expected at least 1 non-BBOT event"
