"""Phase 6 MAP-05 D-06 — one-shot backfill actor.

Idempotent by SELECT predicate (WHERE geo_lat IS NULL). Iterates existing
events with a non-empty raw_stix, calls resolve_geo, UPDATEs coords in
place. Runs once at scheduler startup via DateTrigger.

The _ignore parameter on the Dramatiq actor matches the bootstrap_attack
convention so scheduler._make_dispatch can pass a string arg unchanged.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import dramatiq
from sqlalchemy import create_engine, text, update
from sqlalchemy.orm import Session as SyncSession

from app.models.events import Event

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


@contextmanager
def _open_session() -> Iterator[SyncSession]:
    """Open a sync SQLAlchemy session from the configured DATABASE_URL."""
    from app.config import settings  # lazy import — no circular-import risk

    sync_url = settings.DATABASE_URL
    sync_url = sync_url.replace("postgresql+asyncpg://", "postgresql://")
    sync_url = sync_url.replace("+asyncpg", "")
    engine = create_engine(sync_url, future=True)
    try:
        with SyncSession(engine) as session:
            yield session
    finally:
        engine.dispose()


def backfill_geo_once_impl() -> dict:
    """Scan events with NULL geo coords and resolve via resolve_geo.

    Returns a summary dict: {'scanned': int, 'updated': int, 'skipped': int}.
    Commits after each batch of BATCH_SIZE rows to avoid long-running
    transactions.  Safe to call multiple times — the SELECT predicate
    (geo_lat IS NULL AND geo_lon IS NULL) ensures already-resolved rows
    are never touched.
    """
    from app.services.geo import resolve_geo  # lazy import — MMDB may not exist

    scanned = 0
    updated = 0
    skipped = 0

    # Keyset cursor: start before everything (observed_at = max, id = max uuid)
    # We walk backwards (DESC) to process newest first.
    # cursor_observed_at / cursor_id represent the last row seen.
    cursor_observed_at = None
    cursor_id = None

    with _open_session() as session:
        while True:
            if cursor_observed_at is None:
                # First page — no keyset filter
                rows = session.execute(
                    text("""
                        SELECT id, observed_at, raw_stix
                        FROM events
                        WHERE geo_lat IS NULL
                          AND geo_lon IS NULL
                          AND raw_stix IS NOT NULL
                          AND archived = false
                        ORDER BY observed_at DESC, id DESC
                        LIMIT :batch_size
                    """),
                    {"batch_size": BATCH_SIZE},
                ).all()
            else:
                rows = session.execute(
                    text("""
                        SELECT id, observed_at, raw_stix
                        FROM events
                        WHERE geo_lat IS NULL
                          AND geo_lon IS NULL
                          AND raw_stix IS NOT NULL
                          AND archived = false
                          AND (observed_at, id) < (:cursor_ts, :cursor_id)
                        ORDER BY observed_at DESC, id DESC
                        LIMIT :batch_size
                    """),
                    {
                        "batch_size": BATCH_SIZE,
                        "cursor_ts": cursor_observed_at,
                        "cursor_id": str(cursor_id),
                    },
                ).all()

            if not rows:
                break

            for row in rows:
                scanned += 1
                event_id = row[0]
                raw_stix = row[2]

                lat, lon, cc = resolve_geo(raw_stix)
                if lat is not None and lon is not None:
                    session.execute(
                        update(Event)
                        .where(Event.id == event_id)
                        .values(
                            geo_lat=lat,
                            geo_lon=lon,
                            country_code=cc,
                        )
                    )
                    updated += 1
                else:
                    skipped += 1

                # Advance keyset cursor to last row in this batch
                cursor_observed_at = row[1]
                cursor_id = row[0]

            session.commit()

    logger.info(
        "geo_backfill_done scanned=%d updated=%d skipped=%d",
        scanned,
        updated,
        skipped,
    )
    return {"scanned": scanned, "updated": updated, "skipped": skipped}


@dramatiq.actor(max_retries=0, queue_name="maintenance")
def backfill_geo_once(_ignore: str = "nil") -> None:
    """Dramatiq actor wrapper — enqueued by scheduler at startup.

    The _ignore parameter matches the bootstrap_attack convention so
    scheduler._make_dispatch(backfill_geo_once, "nil") works unchanged.
    """
    backfill_geo_once_impl()
