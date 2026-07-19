"""Social post normaliser - DISINFO-01.

Converts raw Mastodon, 4chan, and Reddit post dicts into the canonical
event row dict accepted by _persist_event_for_bindings.
"""
from __future__ import annotations

import hashlib
import html
import uuid
from datetime import datetime, timezone


def _post_id(post: dict, platform: str) -> str:
    """Extract a stable string ID from a raw post dict."""
    if platform == "4chan":
        return str(post.get("no", post.get("id", "")))
    return str(post.get("id", ""))


def _post_content(post: dict, platform: str) -> str:
    """Extract and decode the main text content from a raw post dict."""
    if platform == "mastodon":
        # Strip basic HTML tags from Mastodon content (e.g. <p>, <br>)
        raw = post.get("content", "") or ""
        # Simple tag-strip - good enough for keyword matching / storage
        import re
        return re.sub(r"<[^>]+>", " ", html.unescape(raw)).strip()
    if platform == "4chan":
        com = post.get("com", "") or ""
        sub = post.get("sub", "") or ""
        return html.unescape((com + " " + sub).strip())
    if platform == "reddit":
        return post.get("selftext", "") or post.get("title", "") or ""
    return post.get("content", "") or post.get("selftext", "") or ""


def _post_title(post: dict, platform: str) -> str:
    """Extract a title (≤200 chars) for the event."""
    if platform == "mastodon":
        content = _post_content(post, platform)
        return content[:200]
    if platform == "4chan":
        sub = post.get("sub", "") or ""
        if sub:
            return html.unescape(sub)[:200]
        content = _post_content(post, platform)
        return content[:200]
    if platform == "reddit":
        return (post.get("title", "") or "")[:200]
    return _post_content(post, platform)[:200]


def _post_observed_at(post: dict, platform: str) -> datetime:
    """Extract observation timestamp from a raw post dict."""
    if platform == "mastodon":
        raw = post.get("created_at", "")
        if isinstance(raw, datetime):
            if raw.tzinfo is None:
                return raw.replace(tzinfo=timezone.utc)
            return raw
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return datetime.now(timezone.utc)
    if platform == "4chan":
        ts = post.get("time") or post.get("created_utc")
        if ts is not None:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        return datetime.now(timezone.utc)
    if platform == "reddit":
        ts = post.get("created_utc")
        if ts is not None:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        raw = post.get("created_at", "")
        if raw:
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt
            except (ValueError, TypeError):
                pass
        return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


def _normalise_social_post(
    post: dict,
    source_id: uuid.UUID,
    platform: str,
) -> dict:
    """Normalise a raw social post dict into a canonical event row.

    Returns a dict suitable for _persist_event_for_bindings with keys:
    source_id, title, description, observed_at, content_hash, tags,
    raw_stix, stix_type, tlp_marking_id.

    content_hash is the first 64 chars of sha256("{platform}:{post_id}").
    """
    post_id = _post_id(post, platform)
    content = _post_content(post, platform)
    title = _post_title(post, platform)
    observed_at = _post_observed_at(post, platform)

    hash_input = f"{platform}:{post_id}"
    content_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:64]

    return {
        "source_id": str(source_id),
        "title": title,
        "description": content,
        "observed_at": observed_at,
        "content_hash": content_hash,
        "tags": [f"social_listening:{platform}"],
        "raw_stix": None,
        "stix_type": None,
        "tlp_marking_id": None,
    }
