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

from app.ingest.normalise import _persist_event_for_bindings, update_source_health
from app.ingest.rss_parser import normalise_rss_entry, parse_rss_feed
from app.services.source_health import update_silent_failure_count, record_ingest_stats

logger = logging.getLogger(__name__)


@contextmanager
def _open_session() -> Iterator[Session]:
    """Sync-engine session per poll — mirrors app.workers.attack_writer pattern.

 Lazily imports settings so `import app.workers.rss` stays cheap
.
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
    parse_ok = 0
    parse_error = 0
    fetch_ok = 0
    fetch_error = 0
    with _open_session() as session:
        src = _fetch_source_row(session, source_id)
        if src is None:
            logger.error("rss_poll_source_missing source_id=%s", source_id)
            return
        try:
            parsed = parse_rss_feed(src["url"])
            fetch_ok = 1
        except Exception as e:  # noqa: BLE001
            fetch_error = 1
            logger.warning("rss_poll_network_error source_id=%s error=%s",
                           source_id, e)
            update_source_health(session, source_id, status="network_error",
                                 succeeded=False)
            try:
                record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                session.commit()
            except Exception as stats_err:  # noqa: BLE001
                logger.warning("record_ingest_stats_failed source_id=%s err=%s", source_id, stats_err)
            return

        if getattr(parsed, "bozo", 0) and not getattr(parsed, "entries", []):
            fetch_error = 1
            fetch_ok = 0
            logger.warning("rss_poll_parse_error source_id=%s error=%s",
                           source_id, getattr(parsed, "bozo_exception", "unknown"))
            update_source_health(session, source_id, status="parse_error",
                                 succeeded=False)
            try:
                record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                session.commit()
            except Exception as stats_err:  # noqa: BLE001
                logger.warning("record_ingest_stats_failed source_id=%s err=%s", source_id, stats_err)
            return

        try:
            for entry in getattr(parsed, "entries", []):
                try:
                    row = normalise_rss_entry(entry, source_id)
                    if row is None:
                        rejected += 1
                        parse_error += 1
                        logger.warning(
                            "feed_item_rejected reason=missing_dedup_key source_id=%s raw_excerpt=%r",
                            source_id,
                            (str(getattr(entry, "title", "") or "")[:100]),
                        )
                        continue
                    rc, _fanout = _persist_event_for_bindings(session, row, source_id)
                    if rc >= 1:
                        inserted += rc
                        parse_ok += 1
                    else:
                        deduped += 1
                        parse_ok += 1
                except Exception as entry_err:  # noqa: BLE001
                    parse_error += 1
                    logger.error(
                        "rss_item_parse_failed source_id=%s entry=%r err=%s",
                        source_id,
                        (str(getattr(entry, "title", "") or "")[:100]),
                        entry_err,
                    )

            update_source_health(session, source_id, status="ok", succeeded=True)
            update_silent_failure_count(session, source_id, inserted)

        finally:
            try:
                record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                session.commit()
            except Exception as stats_err:  # noqa: BLE001
                logger.warning("record_ingest_stats_failed source_id=%s err=%s", source_id, stats_err)

        logger.info(
            "rss_poll_ok source_id=%s inserted=%d deduped=%d rejected=%d",
            source_id, inserted, deduped, rejected,
        )


@dramatiq.actor(max_retries=0, queue_name="ingest")
def poll_rss(source_id: str) -> None:
    poll_rss_impl(source_id)
