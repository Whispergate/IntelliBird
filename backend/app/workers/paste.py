"""Paste-site polling actor — Phase 24 / DARK-03.

RSS-first polling for paste.ee, ghostbin, dpaste.com, rentry.co, controld,
paste.rs. Falls back to trafilatura auto-mode HTML scraping when feedparser
returns bozo=True with zero entries (e.g. paste.rs JSON index).

robots.txt is checked on first poll per domain and cached 24h in Redis
key robots:{domain}. Disallowed paths are skipped silently.

Minimum poll_interval_sec=300 is enforced at source creation (router), not here.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from typing import Iterator
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import dramatiq
import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.ingest.normalise import _persist_event_for_bindings, update_source_health
from app.ingest.rss_parser import normalise_rss_entry, parse_rss_feed
from app.services.source_health import record_ingest_stats, update_silent_failure_count

logger = logging.getLogger(__name__)

_ROBOTS_CACHE_TTL = 86400  # 24h
_ROBOTS_UA = "IntelliBird/1.0"


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
        text("SELECT id, url, opsec_authorised FROM sources WHERE id = :id"),
        {"id": str(source_id)},
    ).one_or_none()
    if row is None:
        return None
    return {"id": row.id, "url": row.url, "opsec_authorised": row.opsec_authorised}


def _robots_allowed(url: str) -> bool:
    """Check robots.txt for url; cached 24h in Redis. Returns True if allowed."""
    from app.services.redis_client import get_redis_client  # noqa: PLC0415

    parsed = urlparse(url)
    domain_key = f"robots:{parsed.netloc}"
    redis = get_redis_client()
    cached = redis.get(domain_key)
    if cached is None:
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            r = httpx.get(robots_url, timeout=10, follow_redirects=True)
            text_body = r.text if r.status_code == 200 else ""
        except Exception:  # noqa: BLE001
            text_body = ""
        redis.set(domain_key, text_body, ex=_ROBOTS_CACHE_TTL)
        cached = text_body
    else:
        cached = cached.decode("utf-8") if isinstance(cached, bytes) else cached

    rp = RobotFileParser()
    rp.set_url(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
    rp.parse(cached.splitlines())
    return rp.can_fetch(_ROBOTS_UA, url)


def poll_paste_impl(source_id_str: str) -> None:
    """Sync actor body — invoked directly by integration tests."""
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
            logger.error("paste_poll_source_missing source_id=%s", source_id)
            return

        if not src.get("opsec_authorised"):
            logger.error(
                "paste_poll_opsec_not_authorised source_id=%s", source_id
            )
            update_source_health(session, source_id, status="config_error", succeeded=False)
            try:
                record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                session.commit()
            except Exception:  # noqa: BLE001
                pass
            return

        if not _robots_allowed(src["url"]):
            logger.warning(
                "paste_poll_robots_disallowed source_id=%s url=%s", source_id, src["url"]
            )
            update_source_health(session, source_id, status="ok", succeeded=True)
            try:
                record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                session.commit()
            except Exception:  # noqa: BLE001
                pass
            return

        # RSS-first
        try:
            parsed = parse_rss_feed(src["url"])
            fetch_ok = 1
        except Exception as e:  # noqa: BLE001
            fetch_error = 1
            logger.warning(
                "paste_poll_network_error source_id=%s err=%s", source_id, e
            )
            update_source_health(session, source_id, status="network_error", succeeded=False)
            try:
                record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                session.commit()
            except Exception:  # noqa: BLE001
                pass
            return

        # Fallback to HTML auto-mode when RSS fails
        entries = getattr(parsed, "entries", [])
        if getattr(parsed, "bozo", 0) and not entries:
            logger.info("paste_poll_rss_fallback_to_html source_id=%s", source_id)
            try:
                from app.ingest.html_scrape_parser import auto_discover_entries, fetch_html  # noqa: PLC0415

                cfg = {"mode": "auto"}
                html_text = fetch_html(src["url"])
                rows_direct = auto_discover_entries(html_text, src["url"], source_id, cfg)
                for row in rows_direct:
                    try:
                        rc, _ = _persist_event_for_bindings(session, row, source_id)
                        if rc >= 1:
                            inserted += rc
                            parse_ok += 1
                        else:
                            deduped += 1
                            parse_ok += 1
                    except Exception as entry_err:  # noqa: BLE001
                        parse_error += 1
                        logger.error(
                            "paste_html_fallback_persist_failed err=%s", entry_err
                        )
                update_source_health(session, source_id, status="ok", succeeded=True)
                update_silent_failure_count(session, source_id, inserted)
            except Exception as fallback_err:  # noqa: BLE001
                fetch_error = 1
                fetch_ok = 0
                logger.warning(
                    "paste_poll_html_fallback_failed source_id=%s err=%s",
                    source_id,
                    fallback_err,
                )
                update_source_health(session, source_id, status="parse_error", succeeded=False)
            finally:
                try:
                    record_ingest_stats(
                        session, source_id, parse_ok, parse_error, fetch_ok, fetch_error
                    )
                    session.commit()
                except Exception:  # noqa: BLE001
                    pass
            return

        # Process RSS entries
        try:
            for entry in entries:
                try:
                    row = normalise_rss_entry(entry, source_id)
                    if row is None:
                        rejected += 1
                        parse_error += 1
                        continue
                    rc, _ = _persist_event_for_bindings(session, row, source_id)
                    if rc >= 1:
                        inserted += rc
                        parse_ok += 1
                    else:
                        deduped += 1
                        parse_ok += 1
                except Exception as entry_err:  # noqa: BLE001
                    parse_error += 1
                    logger.error(
                        "paste_item_parse_failed source_id=%s err=%s", source_id, entry_err
                    )
            update_source_health(session, source_id, status="ok", succeeded=True)
            update_silent_failure_count(session, source_id, inserted)
        finally:
            try:
                record_ingest_stats(
                    session, source_id, parse_ok, parse_error, fetch_ok, fetch_error
                )
                session.commit()
            except Exception:  # noqa: BLE001
                pass

        logger.info(
            "paste_poll_ok source_id=%s inserted=%d deduped=%d rejected=%d",
            source_id,
            inserted,
            deduped,
            rejected,
        )


@dramatiq.actor(max_retries=0, queue_name="darkweb")
def poll_paste(source_id: str) -> None:
    poll_paste_impl(source_id)
