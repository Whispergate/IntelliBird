"""Silent-failure counter maintenance for SRC-06.

Called from each worker's _impl function after a successful batch.
Caller MUST commit the session (mirrors app.ingest.normalise pattern).

State machine:
 inserted_count == 0 → silent_failure_count += 1
 inserted_count >= 1 → silent_failure_count = 0
 inserted_count < 0 → ValueError (caller bug)

Plan 02's _effective_status reads INGEST_SILENT_FAILURE_THRESHOLD and
surfaces 'silent' in SourceResponse when the counter crosses the threshold
AND last_status == 'ok'.

Phase 16 MON-01 / MON-03 extensions:
 record_ingest_stats() — writes one row to source_ingest_stats hypertable per poll
 bump_last_event_at() — sync UPDATE for sources.last_event_at (sync workers)
 async_bump_last_event_at() — async UPDATE for sources.last_event_at (async workers)
"""
from __future__ import annotations

import uuid

from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.models.sources import Source


def update_silent_failure_count(
    session: Session,
    source_id: uuid.UUID,
    inserted_count: int,
) -> None:
    """Increment or reset sources.silent_failure_count. Caller commits.

 State machine:
 - inserted_count == 0 → silent_failure_count = silent_failure_count + 1
 - inserted_count >= 1 → silent_failure_count = 0
 - inserted_count < 0 → raises ValueError

 This function only executes an UPDATE — it does NOT call session.commit.
 The caller (worker _impl success path) owns the transaction boundary.
"""
    if inserted_count < 0:
        raise ValueError(
            f"inserted_count must be >= 0, got {inserted_count!r}"
        )

    if inserted_count == 0:
        values = {"silent_failure_count": Source.silent_failure_count + 1}
    else:
        values = {"silent_failure_count": 0}

    stmt = update(Source).where(Source.id == source_id).values(**values)
    session.execute(stmt)


def bump_last_event_at(session: Session, source_id: uuid.UUID) -> None:
    """Update sources.last_event_at to GREATEST(last_event_at, now()) — sync.

    Called at ingest INSERT sites (sync workers / normalise.py / nvd.py).
    Caller MUST commit. Never decreases last_event_at.
    """
    # Phase 16 MON-01: bump last_event_at after successful insert
    session.execute(
        text(
            "UPDATE sources "
            "SET last_event_at = GREATEST(COALESCE(last_event_at, now()), now()) "
            "WHERE id = :source_id"
        ),
        {"source_id": source_id},
    )


async def async_bump_last_event_at(session: object, source_id: uuid.UUID) -> None:
    """Update sources.last_event_at to GREATEST(last_event_at, now()) — async.

    Called at ingest INSERT sites (async workers / brand_monitor.py / easm.py).
    Caller MUST commit. Never decreases last_event_at.
    Session is typed as ``object`` to avoid a hard import of AsyncSession here;
    callers import AsyncSession themselves and pass the session directly.
    """
    # Phase 16 MON-01: bump last_event_at after successful insert
    await session.execute(
        text(
            "UPDATE sources "
            "SET last_event_at = GREATEST(COALESCE(last_event_at, now()), now()) "
            "WHERE id = :source_id"
        ),
        {"source_id": source_id},
    )


def record_ingest_stats(
    session: Session,
    source_id: uuid.UUID,
    parse_ok: int,
    parse_error: int,
    fetch_ok: int,
    fetch_error: int,
) -> None:
    """INSERT one row into source_ingest_stats at end of poll batch.

    Caller MUST commit. Negative counters silently clamped to 0.
    Writes exactly one row per poll — accumulate counters in-process,
    call once at end of _impl (single INSERT per source per poll batch).
    """
    session.execute(
        text(
            "INSERT INTO source_ingest_stats "
            "(time, source_id, parse_ok, parse_error, fetch_ok, fetch_error) "
            "VALUES (now(), :source_id, :parse_ok, :parse_error, :fetch_ok, :fetch_error)"
        ),
        {
            "source_id": source_id,
            "parse_ok": max(0, parse_ok),
            "parse_error": max(0, parse_error),
            "fetch_ok": max(0, fetch_ok),
            "fetch_error": max(0, fetch_error),
        },
    )
