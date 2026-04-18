"""RSS/Atom polling actor — INGR-01, INGR-02, INGR-03.

poll_rss(source_id) is the Dramatiq actor entrypoint. It delegates to
poll_rss_impl so integration tests can invoke the implementation
synchronously without the Dramatiq actor dispatch layer.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from typing import Iterator

import dramatiq
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.ingest.normalise import _persist_event, update_source_health
from app.ingest.rss_parser import normalise_rss_entry, parse_rss_feed
from app.services.source_health import update_silent_failure_count

logger = logging.getLogger(__name__)


@contextmanager
def _open_session() -> Iterator[Session]:
    """Sync-engine session per poll — mirrors app.workers.attack_writer pattern.

    Lazily imports settings so `import app.workers.rss` stays cheap
    (Phase 1 pattern — see broker.py module docstring).
    """
    from app.config import settings  # noqa: PLC0415
    sync_url = settings.DATABASE_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url, future=True)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def _fetch_source_row(session: Session, source_id: uuid.UUID) -> dict | None:
    """Read sources.{url, credentials_enc} for the given source."""
    row = session.execute(
        text("SELECT id, url, credentials_enc FROM sources WHERE id = :id"),
        {"id": str(source_id)},
    ).one_or_none()
    if row is None:
        return None
    return {"id": row.id, "url": row.url, "credentials_enc": row.credentials_enc}


def poll_rss_impl(source_id_str: str) -> None:
    """Actor body — sync implementation. Called by `poll_rss.send(...)` or
    directly by integration tests.
    """
    source_id = uuid.UUID(source_id_str)
    inserted = 0
    deduped = 0
    rejected = 0
    with _open_session() as session:
        src = _fetch_source_row(session, source_id)
        if src is None:
            logger.error("rss_poll_source_missing source_id=%s", source_id)
            return
        try:
            parsed = parse_rss_feed(src["url"])
        except Exception as e:  # noqa: BLE001
            logger.warning("rss_poll_network_error source_id=%s error=%s",
                           source_id, e)
            update_source_health(session, source_id, status="network_error",
                                 succeeded=False)
            session.commit()
            return

        if getattr(parsed, "bozo", 0) and not getattr(parsed, "entries", []):
            logger.warning("rss_poll_parse_error source_id=%s error=%s",
                           source_id, getattr(parsed, "bozo_exception", "unknown"))
            update_source_health(session, source_id, status="parse_error",
                                 succeeded=False)
            session.commit()
            return

        for entry in getattr(parsed, "entries", []):
            row = normalise_rss_entry(entry, source_id)
            if row is None:
                rejected += 1
                logger.warning(
                    "feed_item_rejected reason=missing_dedup_key source_id=%s raw_excerpt=%r",
                    source_id,
                    (str(getattr(entry, "title", "") or "")[:100]),
                )
                continue
            rc = _persist_event(session, row)
            if rc == 1:
                inserted += 1
            else:
                deduped += 1

        update_source_health(session, source_id, status="ok", succeeded=True)
        update_silent_failure_count(session, source_id, inserted)
        session.commit()
        logger.info(
            "rss_poll_ok source_id=%s inserted=%d deduped=%d rejected=%d",
            source_id, inserted, deduped, rejected,
        )


@dramatiq.actor(max_retries=0, queue_name="ingest")
def poll_rss(source_id: str) -> None:
    poll_rss_impl(source_id)
