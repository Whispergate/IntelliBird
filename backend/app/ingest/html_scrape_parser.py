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
for v1 - see docs/ops/html-scrape-sources.md).

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
AUTO_MODE: str = "auto"
_MIN_AUTO_TITLE_LEN: int = 8


def validate_scrape_config(cfg: dict | None) -> None:
    """Raise ValueError when required selector keys are missing or empty.

    Quick task 260426-aas: when ``cfg["mode"] == "auto"`` the selector check is
    skipped (auto-discovery uses trafilatura - no operator selectors required).
    Rows shipped 2026-04-25 (no ``mode`` key) fall through to manual validation
    so back-compat holds.
    """
    if not isinstance(cfg, dict):
        raise ValueError("scrape_config missing required key: item_selector")
    if cfg.get("mode") == AUTO_MODE:
        return
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


def auto_discover_entries(
    html_text: str,
    base_url: str,
    source_id: uuid.UUID,
    *,
    max_items: int = DEFAULT_MAX_ITEMS,
    user_agent: str = DEFAULT_UA,
    timeout_sec: int = 20,
) -> list[dict]:
    """Quick task 260426-aas: selectorless article discovery.

    Strategy:
      1. Use ``trafilatura.feeds.find_feed_urls`` to detect any RSS/Atom feed
         linked from ``base_url``. If found, parse the first feed via
         ``feedparser`` and emit rows from feed entries.
      2. Fallback: scrape anchors from ``<main>``, ``<article>`` or
         ``[role=main]`` containers and emit one row per unique link.
      3. If both yield zero rows, log and return ``[]`` (no exception).

    Output rows are shaped exactly like the manual-selector path so
    ``_persist_event`` consumes them without branching.
    """
    # Lazy import - manual-mode test runs should not load trafilatura.
    from trafilatura import feeds as _trafilatura_feeds  # noqa: PLC0415

    cap = min(max(int(max_items or DEFAULT_MAX_ITEMS), 1), MAX_ITEMS_HARD_CAP)

    # (1) Feed discovery path.
    feed_urls: list[str] = []
    try:
        result = _trafilatura_feeds.find_feed_urls(base_url, target_lang=None)
        if isinstance(result, list):
            feed_urls = [u for u in result if isinstance(u, str) and u]
        elif isinstance(result, str) and result:
            feed_urls = [result]
    except Exception as e:  # noqa: BLE001
        logger.debug("html_scrape_auto_feed_discover_error url=%r err=%s", base_url, e)

    if feed_urls:
        feed_url = feed_urls[0]
        try:
            feed_text = fetch_html(feed_url, user_agent=user_agent, timeout_sec=timeout_sec)
        except Exception as e:  # noqa: BLE001
            logger.debug("html_scrape_auto_feed_fetch_error url=%r err=%s", feed_url, e)
            feed_text = ""

        if feed_text:
            import feedparser  # noqa: PLC0415

            parsed = feedparser.parse(feed_text)
            entries = list(getattr(parsed, "entries", []) or [])
            if entries:
                rows: list[dict] = []
                for entry in entries:
                    if len(rows) >= cap:
                        break
                    title = (getattr(entry, "title", "") or "").strip()
                    link = (getattr(entry, "link", "") or "").strip()
                    if not title or not link:
                        continue
                    absolute_link = urljoin(base_url, link)
                    if not absolute_link.startswith(("http://", "https://")):
                        continue
                    description: str | None = None
                    summary = getattr(entry, "summary", None)
                    if isinstance(summary, str) and summary.strip():
                        description = summary.strip()
                    observed_at: datetime | None = None
                    pp = getattr(entry, "published_parsed", None) or getattr(
                        entry, "updated_parsed", None
                    )
                    if pp is not None:
                        try:
                            observed_at = datetime(*pp[:6], tzinfo=timezone.utc)  # type: ignore[misc]
                        except Exception:  # noqa: BLE001
                            observed_at = None
                    if observed_at is None:
                        observed_at = datetime.now(timezone.utc)
                    title_clean = title[:_MAX_TITLE_LEN]
                    rows.append(
                        {
                            "stix_type": SCRAPE_STIX_TYPE,
                            "source_id": source_id,
                            "raw_reference": absolute_link,
                            "observed_at": observed_at,
                            "title": title_clean,
                            "description": description,
                            "content_hash": rss_content_hash(
                                str(source_id), absolute_link, title_clean
                            ),
                            "visibility": "shared",
                        }
                    )
                if rows:
                    return rows
                # zero rows from feed → fall through to link extraction.

    # (2) Fallback: anchor extraction from main/article/role=main.
    try:
        root = lxml_html.fromstring(html_text)
    except Exception as e:  # noqa: BLE001
        logger.warning("html_scrape_auto_root_parse_error err=%s", e)
        return []

    try:
        anchors = root.cssselect("main a, article a, [role=main] a")
    except Exception as e:  # noqa: BLE001
        logger.warning("html_scrape_auto_selector_error err=%s", e)
        anchors = []

    seen: set[tuple[str, str]] = set()
    rows = []
    now = datetime.now(timezone.utc)
    for a in anchors:
        if len(rows) >= cap:
            break
        title_raw = (a.text_content() or "").strip()
        href = (a.get("href") or "").strip()
        if not title_raw or not href:
            continue
        if len(title_raw) < _MIN_AUTO_TITLE_LEN:
            continue
        absolute_link = urljoin(base_url, href)
        if not absolute_link.startswith(("http://", "https://")):
            continue
        key = (absolute_link, title_raw.lower())
        if key in seen:
            continue
        seen.add(key)
        title_clean = title_raw[:_MAX_TITLE_LEN]
        rows.append(
            {
                "stix_type": SCRAPE_STIX_TYPE,
                "source_id": source_id,
                "raw_reference": absolute_link,
                "observed_at": now,
                "title": title_clean,
                "description": None,
                "content_hash": rss_content_hash(str(source_id), absolute_link, title_clean),
                "visibility": "shared",
            }
        )

    if not rows:
        logger.info("html_scrape_auto_no_results base_url=%r", base_url)
    return rows


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

    Quick task 260426-aas: when ``scrape_config["mode"] == "auto"`` dispatch to
    ``auto_discover_entries`` (selectorless feed/anchor extraction).
    """
    validate_scrape_config(scrape_config)

    if scrape_config.get("mode") == AUTO_MODE:
        return auto_discover_entries(
            html_text,
            base_url,
            source_id,
            max_items=_resolve_max_items(scrape_config),
            user_agent=scrape_config.get("user_agent") or DEFAULT_UA,
        )

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
            # file://, data:, javascript: etc - skip.
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
