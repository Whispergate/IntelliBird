"""IOC-05 re-sighting upsert integration tests — Plan 22-04 Task 1.

Re-sighting an expired IOC via the upsert path MUST:
  * flip status='expired' → 'active'
  * bump last_seen
  * NEVER change confidence (analyst-set, not auto-inflated — RESEARCH Pitfall 5)
  * append a row to ioc_event_links
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _truncate_iocs(db_session):
    await db_session.execute(
        text("TRUNCATE TABLE ioc_event_links, iocs RESTART IDENTITY CASCADE")
    )
    await db_session.commit()
    yield


def _make_enrichment(ip: str):
    """Lightweight Enrichment-shaped object for the upsert helper."""

    class _E:
        iocs = {"ip": {ip}}

    return _E()


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_resighting_flips_expired_to_active_and_preserves_confidence(db_session):
    """End-to-end: insert an expired IOC, upsert it again, assert status flips,
    last_seen bumps, confidence stays at the analyst-set value, and a link row
    is created.
    """
    from app.services.iocs import upsert_ioc_for_event

    project_id = uuid.uuid4()
    ip = "203.0.113.7"
    two_years_ago = datetime.now(timezone.utc) - timedelta(days=730)

    # Seed project first (FK target), then expired IOC with analyst-set
    # confidence 0.95 — re-sighting must NOT mutate this back to default 0.7.
    await db_session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (:pid, :n, 'internal', :cb, false) ON CONFLICT (id) DO NOTHING"
        ),
        {"pid": project_id, "n": f"resighting-{project_id.hex[:8]}", "cb": str(uuid.uuid4())},
    )
    iid = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO iocs "
            "(id, project_id, type, value, normalized_value, status, confidence, "
            " ttl_days, source, first_seen, last_seen, created_at, updated_at) "
            "VALUES (:id, :pid, 'ip', :v, :nv, 'expired', 0.95, 30, 'manual', "
            ":ts, :ts, :ts, :ts)"
        ),
        {"id": iid, "pid": project_id, "v": ip, "nv": ip, "ts": two_years_ago},
    )
    await db_session.commit()

    # Build a fake event row + Enrichment containing the same IOC value.
    event_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    fake_event = {"id": event_id, "project_id": project_id, "observed_at": now}

    inserted, links = await upsert_ioc_for_event(
        db_session, fake_event, _make_enrichment(ip), source="event",
    )
    await db_session.commit()

    assert inserted == 1, "exactly one IOC upsert expected"
    assert links == 1, "exactly one ioc_event_links row expected on first sighting"

    row = (
        await db_session.execute(
            text(
                "SELECT status, confidence, last_seen FROM iocs WHERE id = :id"
            ),
            {"id": iid},
        )
    ).one()
    assert row.status == "active", "expired IOC must flip to active on re-sighting"
    assert row.confidence == Decimal("0.95"), (
        "re-sighting must NOT change analyst-set confidence "
        f"(got {row.confidence!r})"
    )
    # last_seen advanced to the new event observed_at (use minute resolution).
    assert row.last_seen >= now - timedelta(minutes=1)

    link_count = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM ioc_event_links WHERE ioc_id = :iid"),
            {"iid": iid},
        )
    ).scalar_one()
    assert link_count == 1
