"""Tor-HTML scraping actor — Phase 24 / DARK-02.

Structural clone of html_scrape.py with:
  - httpx.AsyncClient through socks5h://tor:9050 (remote DNS — required for .onion)
  - BFS crawl depth from scrape_config.crawl_depth (default 1, max 3)
  - queue_name="darkweb" so tor-worker handles this queue exclusively
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from collections import deque
from contextlib import contextmanager
from typing import Iterator

import dramatiq
import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.ingest.html_scrape_parser import (
    DEFAULT_UA,
    normalise_scrape_entries,
)
from app.ingest.normalise import _persist_event_for_bindings, update_source_health
from app.services.source_health import record_ingest_stats, update_silent_failure_count

logger = logging.getLogger(__name__)

_TOR_PROXY = f"socks5h://{os.environ.get('TOR_SOCKS5_HOST', 'tor:9050')}"
_ONION_LINK_RE = re.compile(r'href=["\']([^"\']*\.onion[^"\']*)["\']', re.IGNORECASE)
_MAX_CRAWL_DEPTH = 3


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
        text(
            "SELECT id, url, scrape_config, opsec_authorised "
            "FROM sources WHERE id = :id"
        ),
        {"id": str(source_id)},
    ).one_or_none()
    if row is None:
        return None
    return {
        "id": row.id,
        "url": row.url,
        "scrape_config": row.scrape_config,
        "opsec_authorised": row.opsec_authorised,
    }


async def _async_fetch_onion(url: str, *, user_agent: str, timeout_sec: int = 60) -> str:
    """Fetch a single .onion URL via socks5h proxy (remote DNS)."""
    headers = {"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"}
    async with httpx.AsyncClient(
        proxies={"all://": _TOR_PROXY},
        follow_redirects=True,
        headers=headers,
        timeout=timeout_sec,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


def _extract_onion_links(html: str, base_url: str) -> list[str]:
    """Extract absolute .onion hrefs from HTML."""
    from urllib.parse import urlparse  # noqa: PLC0415

    links: list[str] = []
    for m in _ONION_LINK_RE.finditer(html):
        href = m.group(1)
        if href.startswith("http"):
            links.append(href)
        elif href.startswith("/"):
            p = urlparse(base_url)
            links.append(f"{p.scheme}://{p.netloc}{href}")
    return links


async def _async_crawl(
    seed_url: str, depth: int, *, user_agent: str
) -> list[tuple[str, str]]:
    """BFS crawl; returns list of (url, html_text) pairs."""
    depth = min(depth, _MAX_CRAWL_DEPTH)
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(seed_url, 0)])
    results: list[tuple[str, str]] = []
    while queue:
        url, current_depth = queue.popleft()
        if url in visited or current_depth > depth:
            continue
        visited.add(url)
        try:
            html = await _async_fetch_onion(url, user_agent=user_agent)
            results.append((url, html))
            if current_depth < depth:
                for link in _extract_onion_links(html, url):
                    if link not in visited:
                        queue.append((link, current_depth + 1))
        except Exception as e:  # noqa: BLE001
            logger.warning("tor_html_crawl_fetch_failed url=%s err=%s", url, e)
    return results


def poll_tor_html_impl(source_id_str: str) -> None:
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
            logger.error("tor_html_poll_source_missing source_id=%s", source_id)
            return

        if not src.get("opsec_authorised"):
            logger.error(
                "tor_html_poll_opsec_not_authorised source_id=%s", source_id
            )
            update_source_health(session, source_id, status="config_error", succeeded=False)
            try:
                record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                session.commit()
            except Exception:  # noqa: BLE001
                pass
            return

        cfg = src["scrape_config"] or {}
        user_agent = cfg.get("user_agent") or DEFAULT_UA
        crawl_depth = min(int(cfg.get("crawl_depth", 1)), _MAX_CRAWL_DEPTH)

        try:
            pages = asyncio.run(
                _async_crawl(src["url"], crawl_depth, user_agent=user_agent)
            )
            fetch_ok = 1
        except Exception as e:  # noqa: BLE001
            fetch_error = 1
            logger.warning(
                "tor_html_poll_network_error source_id=%s err=%s", source_id, e
            )
            update_source_health(session, source_id, status="network_error", succeeded=False)
            try:
                record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                session.commit()
            except Exception:  # noqa: BLE001
                pass
            return

        try:
            for page_url, html_text in pages:
                try:
                    scrape_cfg = cfg if cfg else {"mode": "auto"}
                    rows = normalise_scrape_entries(html_text, page_url, source_id, scrape_cfg)
                    for row in rows:
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
                                "tor_html_item_persist_failed source_id=%s err=%s",
                                source_id,
                                entry_err,
                            )
                except Exception as page_err:  # noqa: BLE001
                    parse_error += 1
                    logger.warning(
                        "tor_html_page_parse_failed url=%s err=%s", page_url, page_err
                    )

            update_source_health(session, source_id, status="ok", succeeded=True)
            update_silent_failure_count(session, source_id, inserted)
        finally:
            try:
                record_ingest_stats(
                    session, source_id, parse_ok, parse_error, fetch_ok, fetch_error
                )
                session.commit()
            except Exception as stats_err:  # noqa: BLE001
                logger.warning(
                    "record_ingest_stats_failed source_id=%s err=%s", source_id, stats_err
                )

        logger.info(
            "tor_html_poll_ok source_id=%s inserted=%d deduped=%d parse_error=%d",
            source_id,
            inserted,
            deduped,
            parse_error,
        )


@dramatiq.actor(max_retries=0, queue_name="darkweb")
def poll_tor_html(source_id: str) -> None:
    poll_tor_html_impl(source_id)
