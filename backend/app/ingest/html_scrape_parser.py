"""HTML scrape → canonical Event row dicts (quick task 260425-ovt).

A "scraped feed" turns any server-rendered webpage into a feed by applying
operator-supplied CSS selectors. Reuses:

  - ``rss_content_hash(source_id, link, title)`` for dedup so the existing
    UNIQUE (source_id, content_hash, observed_at) index on events absorbs
    re-polls naturally.
  - The same row-dict shape consumed by ``app.ingest.normalise._persist_event``
    (only ``stix_type`` differs: ``x-intellibird-html-scrape``).

Scope: server-rendered HTML only. Pages that require JavaScript to render the
items selector will yield zero entries (a JS-rendering sidecar is out of scope
for v1 — see docs/ops/html-scrape-sources.md).

Selector syntax: a trailing ``@attr`` extracts the attribute (``h2 a@href``);
without it the selector returns ``element.text_content().strip()``.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import httpx
from lxml import html as lxml_html  # type: ignore[import-untyped]

from app.ingest.dedup import rss_content_hash

logger = logging.getLogger(__name__)

SCRAPE_STIX_TYPE: str = "x-intellibird-html-scrape"
REQUIRED_KEYS: tuple[str, ...] = ("item_selector", "title_selector", "link_selector")
DEFAULT_UA: str = "IntelliBird/1.0 (+self-hosted)"
MAX_ITEMS_HARD_CAP: int = 200
DEFAULT_MAX_ITEMS: int = 50
_MAX_TITLE_LEN: int = 2048


def validate_scrape_config(cfg: dict | None) -> None:
    """Raise ValueError when required selector keys are missing or empty."""
    if not isinstance(cfg, dict):
        raise ValueError("scrape_config missing required key: item_selector")
    for key in REQUIRED_KEYS:
        val = cfg.get(key)
        if not isinstance(val, str) or not val.strip():
            raise ValueError(f"scrape_config missing required key: {key}")


def _split_selector(selector: str) -> tuple[str, str | None]:
    """Split a ``"sel@attr"`` selector into (sel, attr|None).

    rsplit on '@' so attribute names containing '@' are unsupported (fine for
    HTML attrs; matches how feedparser/scrapy pseudo-selectors are conventionally
    written).
    """
    if "@" in selector:
        sel, attr = selector.rsplit("@", 1)
        return sel.strip(), attr.strip() or None
    return selector.strip(), None


def _extract(node: Any, selector: str) -> str | None:
    """Apply ``selector`` to ``node`` and return text or attribute value.

    Returns None when the selector matches nothing.
    """
    sel, attr = _split_selector(selector)
    try:
        matches = node.cssselect(sel)
    except Exception as e:  # noqa: BLE001
        logger.debug("html_scrape_selector_error selector=%r err=%s", selector, e)
        return None
    if not matches:
        return None
    first = matches[0]
    if attr is not None:
        val = first.get(attr)
        return val.strip() if isinstance(val, str) else None
    text = first.text_content() or ""
    return text.strip() or None


def _parse_date(raw: str | None, fmt: str | None) -> datetime | None:
    """Try ``fmt`` (strptime) first, then ISO-8601. Always returns tz-aware UTC."""
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    if fmt:
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception as e:  # noqa: BLE001
            logger.debug("html_scrape_date_strptime_failed raw=%r fmt=%r err=%s", raw, fmt, e)
    # ISO-8601 fallback. fromisoformat in 3.11+ accepts most ISO forms; normalise
    # the trailing Z which fromisoformat does not handle pre-3.11.
    iso_candidate = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso_candidate)
    except Exception:  # noqa: BLE001
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fetch_html(
    url: str,
    *,
    user_agent: str = DEFAULT_UA,
    timeout_sec: int = 20,
) -> str:
    """Fetch HTML over HTTP(S). Raises on non-2xx (caller handles)."""
    headers = {"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"}
    with httpx.Client(follow_redirects=True, headers=headers, timeout=timeout_sec) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text


def _resolve_max_items(cfg: dict) -> int:
    raw = cfg.get("max_items")
    if raw is None:
        return DEFAULT_MAX_ITEMS
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_ITEMS
    if n <= 0:
        return DEFAULT_MAX_ITEMS
    return min(n, MAX_ITEMS_HARD_CAP)


def normalise_scrape_entries(
    html_text: str,
    base_url: str,
    source_id: uuid.UUID,
    scrape_config: dict,
) -> list[dict]:
    """Apply selectors and return a list of Event row dicts ready for _persist_event.

    Items with empty title or empty link are silently filtered (caller treats
    the count drop as parse_error if it cares to). max_items is enforced server
    side and clamped to MAX_ITEMS_HARD_CAP.
    """
    validate_scrape_config(scrape_config)

    item_selector = scrape_config["item_selector"]
    title_selector = scrape_config["title_selector"]
    link_selector = scrape_config["link_selector"]
    date_selector = scrape_config.get("date_selector")
    date_format = scrape_config.get("date_format")
    summary_selector = scrape_config.get("summary_selector")
    cap = _resolve_max_items(scrape_config)

    try:
        root = lxml_html.fromstring(html_text)
    except Exception as e:  # noqa: BLE001
        logger.warning("html_scrape_root_parse_error err=%s", e)
        return []

    rows: list[dict] = []
    try:
        items = root.cssselect(item_selector)
    except Exception as e:  # noqa: BLE001
        logger.warning("html_scrape_item_selector_error selector=%r err=%s", item_selector, e)
        return []

    for node in items:
        if len(rows) >= cap:
            break
        title = _extract(node, title_selector)
        link = _extract(node, link_selector)
        if not title or not link:
            continue
        # Resolve relative URLs against the source's base URL.
        absolute_link = urljoin(base_url, link.strip())
        if not absolute_link.startswith(("http://", "https://")):
            # file://, data:, javascript: etc — skip.
            continue

        observed_at: datetime | None = None
        if date_selector:
            raw_date = _extract(node, date_selector)
            observed_at = _parse_date(raw_date, date_format)
        if observed_at is None:
            observed_at = datetime.now(timezone.utc)

        description: str | None = None
        if summary_selector:
            description = _extract(node, summary_selector)

        title_clean = title.strip()[:_MAX_TITLE_LEN]

        rows.append(
            {
                "stix_type": SCRAPE_STIX_TYPE,
                "source_id": source_id,
                "raw_reference": absolute_link,
                "observed_at": observed_at,
                "title": title_clean,
                "description": description,
                "content_hash": rss_content_hash(str(source_id), absolute_link, title_clean),
                "visibility": "shared",
            }
        )
    return rows
