"""HTML-scrape polling actor — quick task 260425-ovt.

Mirrors app.workers.rss control flow exactly so the existing health/stats
plumbing applies unchanged. Differences vs poll_rss:

  - Reads sources.scrape_config alongside url.
  - Calls fetch_html + normalise_scrape_entries instead of feedparser.parse.
  - Missing/invalid scrape_config → status='parse_error' + fetch_error=1, return.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from typing import Iterator

import dramatiq
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.ingest.html_scrape_parser import (
    DEFAULT_UA,
    fetch_html,
    normalise_scrape_entries,
    validate_scrape_config,
)
from app.ingest.normalise import _persist_event, update_source_health
from app.services.source_health import record_ingest_stats, update_silent_failure_count

logger = logging.getLogger(__name__)


@contextmanager
def _open_session() -> Iterator[Session]:
    from app.config import settings  # noqa: PLC0415

    sync_url = settings.DATABASE_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url, future=True)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def _fetch_source_row(session: Session, source_id: uuid.UUID) -> dict | None:
    row = session.execute(
        text("SELECT id, url, scrape_config FROM sources WHERE id = :id"),
        {"id": str(source_id)},
    ).one_or_none()
    if row is None:
        return None
    return {"id": row.id, "url": row.url, "scrape_config": row.scrape_config}


def _record_stats(session: Session, source_id: uuid.UUID, *, parse_ok: int, parse_error: int,
                  fetch_ok: int, fetch_error: int) -> None:
    try:
        record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
        session.commit()
    except Exception as stats_err:  # noqa: BLE001
        logger.warning("record_ingest_stats_failed source_id=%s err=%s", source_id, stats_err)


def poll_html_scrape_impl(source_id_str: str) -> None:
    """Sync actor body — invoked directly by integration tests."""
    source_id = uuid.UUID(source_id_str)
    inserted = 0
    deduped = 0
    parse_ok = 0
    parse_error = 0
    fetch_ok = 0
    fetch_error = 0

    with _open_session() as session:
        src = _fetch_source_row(session, source_id)
        if src is None:
            logger.error("html_scrape_poll_source_missing source_id=%s", source_id)
            return

        cfg = src["scrape_config"]
        try:
            validate_scrape_config(cfg)
        except ValueError as e:
            fetch_error = 1
            logger.warning(
                "html_scrape_poll_config_error source_id=%s err=%s", source_id, e
            )
            update_source_health(session, source_id, status="parse_error", succeeded=False)
            _record_stats(
                session, source_id,
                parse_ok=parse_ok, parse_error=parse_error,
                fetch_ok=fetch_ok, fetch_error=fetch_error,
            )
            return

        # mypy: validate_scrape_config guarantees cfg is a dict at this point.
        assert isinstance(cfg, dict)
        user_agent = cfg.get("user_agent") or DEFAULT_UA

        try:
            html_text = fetch_html(src["url"], user_agent=user_agent)
            fetch_ok = 1
        except Exception as e:  # noqa: BLE001
            fetch_error = 1
            logger.warning(
                "html_scrape_poll_network_error source_id=%s error=%s", source_id, e
            )
            update_source_health(session, source_id, status="network_error", succeeded=False)
            _record_stats(
                session, source_id,
                parse_ok=parse_ok, parse_error=parse_error,
                fetch_ok=fetch_ok, fetch_error=fetch_error,
            )
            return

        try:
            try:
                rows = normalise_scrape_entries(html_text, src["url"], source_id, cfg)
            except Exception as e:  # noqa: BLE001
                fetch_error = 1
                fetch_ok = 0
                logger.warning(
                    "html_scrape_poll_parse_error source_id=%s err=%s", source_id, e
                )
                update_source_health(session, source_id, status="parse_error", succeeded=False)
                return

            for row in rows:
                try:
                    rc = _persist_event(session, row)
                    if rc == 1:
                        inserted += 1
                        parse_ok += 1
                    else:
                        deduped += 1
                        parse_ok += 1
                except Exception as entry_err:  # noqa: BLE001
                    parse_error += 1
                    logger.error(
                        "html_scrape_item_persist_failed source_id=%s title=%r err=%s",
                        source_id,
                        (str(row.get("title", ""))[:100]),
                        entry_err,
                    )

            update_source_health(session, source_id, status="ok", succeeded=True)
            update_silent_failure_count(session, source_id, inserted)
        finally:
            _record_stats(
                session, source_id,
                parse_ok=parse_ok, parse_error=parse_error,
                fetch_ok=fetch_ok, fetch_error=fetch_error,
            )

        logger.info(
            "html_scrape_poll_ok source_id=%s inserted=%d deduped=%d parse_error=%d",
            source_id, inserted, deduped, parse_error,
        )


@dramatiq.actor(max_retries=0, queue_name="ingest")
def poll_html_scrape(source_id: str) -> None:
    poll_html_scrape_impl(source_id)
