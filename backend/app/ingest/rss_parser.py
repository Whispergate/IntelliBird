"""RSS/Atom → canonical Event row dict.

INGR-02: normalise into canonical STIX 2.1-aligned schema with
source_id, observed_at, raw content reference, and extracted link.
: Entries missing both link and id are dropped (returns None) —
the caller logs a WARNING so operators see broken feeds.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import feedparser

from app.ingest.dedup import rss_content_hash

_STIX_TYPE = "x-intellibird-rss"
_MAX_TITLE_LEN = 2048


def parse_rss_feed(
    url_or_path: str,
    *,
    etag: str | None = None,
    modified: str | None = None,
) -> Any:
    """Fetch RSS/Atom from url or parse from local path. Returns FeedParserDict.

 `etag` + `modified` enable HTTP conditional GET for 304 Not Modified.
 Over local file paths these are ignored by feedparser.
"""
    return feedparser.parse(url_or_path, etag=etag, modified=modified)


def _struct_time_to_utc(st: Any) -> datetime:
    """feedparser's published_parsed / updated_parsed is a time.struct_time in UTC."""
    return datetime(
        st.tm_year, st.tm_mon, st.tm_mday,
        st.tm_hour, st.tm_min, st.tm_sec,
        tzinfo=timezone.utc,
    )


def normalise_rss_entry(entry: Any, source_id: uuid.UUID) -> dict | None:
    """Normalise one feedparser entry to an Event row dict.

 Returns None when the entry is unhashable: neither link nor id
 present, or title is empty after stripping. Caller MUST log a
 structured WARNING before discarding.
"""
    # Use dict-get so we work on both FeedParserDict and plain dicts (tests).
    get = entry.get if hasattr(entry, "get") else (lambda k, default=None: entry.get(k, default))

    link = (get("link") or get("id") or "").strip()
    title = (get("title") or "").strip()
    if not link or not title:
        return None

    # Timestamp precedence: published_parsed → updated_parsed → now(UTC)
    pub = get("published_parsed") or get("updated_parsed")
    if pub is not None:
        observed_at = _struct_time_to_utc(pub)
    else:
        observed_at = datetime.now(timezone.utc)

    return {
        "stix_type": _STIX_TYPE,
        "source_id": source_id,
        "raw_reference": link,
        "observed_at": observed_at,
        "title": title[:_MAX_TITLE_LEN],
        "description": (get("summary") or None),
        "content_hash": rss_content_hash(str(source_id), link, title),
        "visibility": "shared",
    }
