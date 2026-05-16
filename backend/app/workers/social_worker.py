"""Social listening polling actor — DISINFO-01.

poll_social(source_id) is the Dramatiq actor entrypoint.  It delegates to
poll_social_impl so integration tests can invoke the implementation
synchronously without the Dramatiq actor dispatch layer.

Supported platforms: mastodon, 4chan, reddit.
Twitter/X requires a paid API tier — see docs/ops/social-sources.md.
"""
from __future__ import annotations

import html
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

import dramatiq
import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.ingest.normalise import _persist_event_for_bindings, update_source_health
from app.ingest.social_normalise import _normalise_social_post
from app.services.source_health import update_silent_failure_count, record_ingest_stats

logger = logging.getLogger(__name__)

_REDDIT_USER_AGENT = "IntelliBird/4.0 (self-hosted threat intelligence platform)"


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


@contextmanager
def _open_session() -> Iterator[Session]:
    """Sync-engine session per poll — mirrors app.workers.rss pattern.

    Lazily imports settings so ``import app.workers.social_worker`` stays cheap.
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
    """Read sources fields for the given source, including source_config."""
    row = session.execute(
        text(
            "SELECT id, url, credentials_enc, source_config "
            "FROM sources WHERE id = :id"
        ),
        {"id": str(source_id)},
    ).one_or_none()
    if row is None:
        return None
    src_config: dict = row.source_config or {}
    return {
        "id": row.id,
        "url": row.url,
        "credentials_enc": row.credentials_enc,
        "source_config": src_config,
        # Expose platform at top level for convenience / patching in tests
        "platform": src_config.get("platform", ""),
    }


# ---------------------------------------------------------------------------
# Platform-specific fetchers
# ---------------------------------------------------------------------------


def _fetch_mastodon_posts(src: dict) -> list[dict]:
    """Fetch public timeline posts from a Mastodon instance.

    Uses Mastodon.py sync client.  Filters by topic_keywords if configured.
    """
    from mastodon import Mastodon  # noqa: PLC0415

    src_config = src.get("source_config") or {}
    instance_url = src_config.get("instance_url") or src.get("url") or "https://mastodon.social"
    topic_keywords: list[str] = [kw.lower() for kw in (src_config.get("topic_keywords") or [])]

    client = Mastodon(api_base_url=instance_url, request_timeout=10)
    raw_posts = client.timeline_public(limit=40)

    posts: list[dict] = []
    for item in raw_posts or []:
        # Mastodon.py returns Mastodon dicts or AttribAccessDict objects
        if hasattr(item, "__getitem__"):
            post_id = str(item.get("id", ""))
            content = item.get("content", "") or ""
            created_at = item.get("created_at", datetime.now(timezone.utc))
            url = item.get("url", "")
        else:
            # AttribAccessDict / object attribute access
            post_id = str(getattr(item, "id", ""))
            content = getattr(item, "content", "") or ""
            created_at = getattr(item, "created_at", datetime.now(timezone.utc))
            url = getattr(item, "url", "")

        post = {
            "id": post_id,
            "content": content,
            "created_at": created_at,
            "url": url,
        }

        if topic_keywords:
            import re  # noqa: PLC0415
            plain = re.sub(r"<[^>]+>", " ", html.unescape(content)).lower()
            if not any(kw in plain for kw in topic_keywords):
                continue

        posts.append(post)

    return posts


def _fetch_4chan_posts(src: dict) -> list[dict]:
    """Fetch OP posts from a 4chan board catalog.

    GETs https://a.4cdn.org/{board}/catalog.json and flattens page threads.
    HTML entities in 'com' and 'sub' are decoded.
    """
    src_config = src.get("source_config") or {}
    board = src_config.get("board", "g")
    topic_keywords: list[str] = [kw.lower() for kw in (src_config.get("topic_keywords") or [])]

    url = f"https://a.4cdn.org/{board}/catalog.json"
    response = httpx.get(url, timeout=15)
    response.raise_for_status()
    pages = response.json()

    posts: list[dict] = []
    for page in pages:
        for thread in page.get("threads", []):
            no = thread.get("no")
            if no is None:
                continue
            com = thread.get("com", "") or ""
            sub = thread.get("sub", "") or ""
            content = html.unescape((com + " " + sub).strip())
            ts = thread.get("time")
            created_at = (
                datetime.fromtimestamp(float(ts), tz=timezone.utc)
                if ts is not None
                else datetime.now(timezone.utc)
            )
            post = {
                "id": str(no),
                "no": no,
                "com": com,
                "sub": sub,
                "content": content,
                "time": ts,
                "created_at": created_at,
                "board": board,
            }

            if topic_keywords:
                if not any(kw in content.lower() for kw in topic_keywords):
                    continue

            posts.append(post)

    return posts


def _fetch_reddit_posts(src: dict) -> list[dict]:
    """Fetch new posts from a Reddit subreddit.

    GETs https://www.reddit.com/r/{subreddit}/new.json?limit=25 with the
    IntelliBird User-Agent to avoid Reddit's bot detection.
    """
    src_config = src.get("source_config") or {}
    subreddit = src_config.get("subreddit", "netsec")
    topic_keywords: list[str] = [kw.lower() for kw in (src_config.get("topic_keywords") or [])]

    url = f"https://www.reddit.com/r/{subreddit}/new.json?limit=25"
    response = httpx.get(
        url,
        headers={"User-Agent": _REDDIT_USER_AGENT},
        timeout=15,
        follow_redirects=True,
    )
    response.raise_for_status()
    data = response.json()

    children = data.get("data", {}).get("children", [])
    posts: list[dict] = []
    for child in children:
        item = child.get("data", {})
        post_id = item.get("id", "")
        title = item.get("title", "") or ""
        selftext = item.get("selftext", "") or ""
        created_utc = item.get("created_utc")
        permalink = item.get("permalink", "")

        post = {
            "id": f"t3_{post_id}",
            "title": title,
            "selftext": selftext,
            "created_utc": created_utc,
            "permalink": permalink,
        }

        if topic_keywords:
            searchable = (title + " " + selftext).lower()
            if not any(kw in searchable for kw in topic_keywords):
                continue

        posts.append(post)

    return posts


def _fetch_posts(src: dict) -> list[dict]:
    """Dispatch to the correct platform fetcher based on src['platform']."""
    platform = src.get("platform") or (src.get("source_config") or {}).get("platform", "")
    if platform == "mastodon":
        return _fetch_mastodon_posts(src)
    if platform == "4chan":
        return _fetch_4chan_posts(src)
    if platform == "reddit":
        return _fetch_reddit_posts(src)
    raise ValueError(f"Unknown social platform: {platform!r}")


# ---------------------------------------------------------------------------
# Main implementation
# ---------------------------------------------------------------------------


def poll_social_impl(source_id_str: str) -> None:
    """Actor body — sync implementation.  Called by ``poll_social.send(...)``
    or directly by integration tests.
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
            logger.error("social_poll_source_missing source_id=%s", source_id)
            return

        platform = src.get("platform") or (src.get("source_config") or {}).get("platform", "unknown")

        # Fetch posts from the platform
        try:
            posts = _fetch_posts(src)
            fetch_ok = 1
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                fetch_error = 1
                logger.warning(
                    "social_poll_rate_limited platform=%s source_id=%s",
                    platform, source_id,
                )
                update_source_health(session, source_id, status="rate_limited", succeeded=False)
                try:
                    record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                    session.commit()
                except Exception as stats_err:  # noqa: BLE001
                    logger.warning(
                        "record_ingest_stats_failed source_id=%s err=%s", source_id, stats_err
                    )
                return
            else:
                fetch_error = 1
                logger.warning(
                    "social_poll_network_error platform=%s source_id=%s error=%s",
                    platform, source_id, exc,
                )
                update_source_health(session, source_id, status="network_error", succeeded=False)
                try:
                    record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                    session.commit()
                except Exception as stats_err:  # noqa: BLE001
                    logger.warning(
                        "record_ingest_stats_failed source_id=%s err=%s", source_id, stats_err
                    )
                return
        except Exception as exc:  # noqa: BLE001
            fetch_error = 1
            logger.warning(
                "social_poll_network_error platform=%s source_id=%s error=%s",
                platform, source_id, exc,
            )
            update_source_health(session, source_id, status="network_error", succeeded=False)
            try:
                record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                session.commit()
            except Exception as stats_err:  # noqa: BLE001
                logger.warning(
                    "record_ingest_stats_failed source_id=%s err=%s", source_id, stats_err
                )
            return

        # Persist each post
        try:
            for post in posts:
                try:
                    row = _normalise_social_post(post, source_id, platform)
                    rc, _fanout = _persist_event_for_bindings(session, row, source_id)
                    if rc >= 1:
                        inserted += rc
                        parse_ok += 1
                        # Enqueue AI narrative classification (optional — do not fail ingest)
                        if rc >= 1:
                            try:
                                from app.workers.ai import suggest_for_event  # noqa: PLC0415
                                # Look up the event id by content_hash for AI enqueue
                                event_row = session.execute(
                                    text(
                                        "SELECT e.id, b.project_id "
                                        "FROM events e "
                                        "JOIN event_project_bindings b ON b.event_id = e.id "
                                        "WHERE e.source_id = :source_id "
                                        "  AND e.content_hash = :content_hash "
                                        "LIMIT 1"
                                    ),
                                    {
                                        "source_id": str(source_id),
                                        "content_hash": row["content_hash"],
                                    },
                                ).one_or_none()
                                if event_row is not None:
                                    suggest_for_event.send(
                                        str(event_row.id), str(event_row.project_id)
                                    )
                            except Exception:  # noqa: BLE001
                                pass  # AI pipeline optional — do not fail ingest
                    else:
                        deduped += 1
                        parse_ok += 1
                except Exception as entry_err:  # noqa: BLE001
                    parse_error += 1
                    rejected += 1
                    logger.warning(
                        "social_post_parse_failed platform=%s source_id=%s err=%s",
                        platform, source_id, entry_err,
                    )

            update_source_health(session, source_id, status="ok", succeeded=True)
            update_silent_failure_count(session, source_id, inserted)

        finally:
            try:
                record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                session.commit()
            except Exception as stats_err:  # noqa: BLE001
                logger.warning(
                    "record_ingest_stats_failed source_id=%s err=%s", source_id, stats_err
                )

        logger.info(
            "social_poll_ok platform=%s source_id=%s inserted=%d deduped=%d rejected=%d",
            platform, source_id, inserted, deduped, rejected,
        )


@dramatiq.actor(max_retries=0, queue_name="ingest")
def poll_social(source_id: str) -> None:
    poll_social_impl(source_id)
