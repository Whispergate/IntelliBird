"""IOC-08 ingest-time IOC + link writer integration tests — Plan 22-04 Task 2.

Verifies that `_persist_event` (sync) writes IOC rows + ioc_event_links rows
for indicators discovered in title/description, and that re-ingesting an event
with the same IOC value upserts (one IOC, two links).
"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as SyncSession

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _truncate_iocs(db_session):
    await db_session.execute(
        text("TRUNCATE TABLE ioc_event_links, iocs RESTART IDENTITY CASCADE")
    )
    await db_session.commit()
    yield


def _sync_engine_from(async_url: str):
    """Convert the asyncpg URL the testcontainer exposes into a sync engine."""
    sync_url = async_url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "+asyncpg", ""
    )
    return create_engine(sync_url, future=True)


def _ingest_event(sync_session: SyncSession, project_id, title: str) -> uuid.UUID:
    """Drive the production ingest writer (`_persist_event`) directly so the
    real IOC hook fires."""
    from app.ingest.normalise import _persist_event

    eid = uuid.uuid4()
    obs = datetime.now(timezone.utc)
    ch = hashlib.sha256(f"{eid}-{title}".encode()).hexdigest()
    row = {
        "id": eid,
        "stix_type": "observed-data",
        "project_id": project_id,
        "observed_at": obs,
        "title": title,
        "content_hash": ch,
        "visibility": "shared",
    }
    inserted = _persist_event(sync_session, row)
    assert inserted == 1, "test fixture event should have inserted"
    sync_session.commit()
    return eid


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_event_persist_writes_ioc_and_link(db_session):
    """A new event with `1.2.3.4` in the title results in iocs + link rows."""
    from app.config import settings

    # Seed project via the async session.
    project_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (:pid, :n, 'internal', :cb, false)"
        ),
        {"pid": project_id, "n": f"ingest-{project_id.hex[:8]}", "cb": str(uuid.uuid4())},
    )
    await db_session.commit()

    # Drive _persist_event with a sync session against the same testcontainer DB.
    engine = _sync_engine_from(settings.DATABASE_URL)
    try:
        with SyncSession(engine) as sync:
            event_id = _ingest_event(sync, project_id, "malicious 1.2.3.4 sighting")
    finally:
        engine.dispose()

    # Verify iocs row exists for ('ip', '1.2.3.4', project_id).
    ioc_row = (
        await db_session.execute(
            text(
                "SELECT id FROM iocs WHERE project_id = :pid AND type = 'ip' "
                "AND normalized_value = '1.2.3.4'"
            ),
            {"pid": project_id},
        )
    ).first()
    assert ioc_row is not None, "ingest hook must write IOC row"

    link_count = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM ioc_event_links WHERE event_id = :eid"),
            {"eid": event_id},
        )
    ).scalar_one()
    assert link_count >= 1, "ingest hook must write ioc_event_links row"


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_second_event_with_same_ioc_appends_link(db_session):
    """Two events sharing one IOC → one IOC row, two link rows."""
    from app.config import settings

    project_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (:pid, :n, 'internal', :cb, false)"
        ),
        {"pid": project_id, "n": f"ingest2-{project_id.hex[:8]}", "cb": str(uuid.uuid4())},
    )
    await db_session.commit()

    engine = _sync_engine_from(settings.DATABASE_URL)
    try:
        with SyncSession(engine) as sync:
            _ingest_event(sync, project_id, "first sighting 5.6.7.8")
            _ingest_event(sync, project_id, "second sighting 5.6.7.8")
    finally:
        engine.dispose()

    ioc_count = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM iocs WHERE project_id = :pid AND type = 'ip' "
                "AND normalized_value = '5.6.7.8'"
            ),
            {"pid": project_id},
        )
    ).scalar_one()
    assert ioc_count == 1, "the same IOC must dedup via UNIQUE constraint"

    link_count = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM ioc_event_links l JOIN iocs i ON i.id = l.ioc_id "
                "WHERE i.project_id = :pid AND i.normalized_value = '5.6.7.8'"
            ),
            {"pid": project_id},
        )
    ).scalar_one()
    assert link_count == 2, f"expected 2 link rows, got {link_count}"
