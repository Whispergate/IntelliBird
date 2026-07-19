"""Unit tests for the auto-discovery branch of html_scrape_parser.

Quick task 260426-aas: paste a URL, system auto-discovers articles either via
RSS/Atom feed (preferred) or by extracting anchors from the page's main-content
container.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.ingest import html_scrape_parser as parser_mod
from app.ingest.html_scrape_parser import (
    AUTO_MODE,
    SCRAPE_STIX_TYPE,
    auto_discover_entries,
    normalise_scrape_entries,
    validate_scrape_config,
)

BASE_URL = "https://example.test/"
SOURCE_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


# ---------------------------------------------------------------------------
# validate_scrape_config - mode dispatch
# ---------------------------------------------------------------------------


def test_validate_auto_mode_skips_required_keys() -> None:
    # No selectors at all - auto mode bypasses the REQUIRED_KEYS check.
    assert validate_scrape_config({"mode": AUTO_MODE}) is None


def test_validate_manual_mode_unchanged() -> None:
    with pytest.raises(ValueError, match="item_selector"):
        validate_scrape_config({"mode": "manual"})


def test_validate_no_mode_back_compat() -> None:
    cfg = {"item_selector": "x", "title_selector": "y", "link_selector": "z"}
    assert validate_scrape_config(cfg) is None


# ---------------------------------------------------------------------------
# auto_discover_entries - fallback link extraction
# ---------------------------------------------------------------------------

_PAGE_NO_FEED_HTML = """
<html><head></head><body>
<main>
  <article><a href="/post-1">Post Number One Headline</a></article>
  <article><a href="/post-2">Post Number Two Headline</a></article>
</main>
</body></html>
"""


def test_auto_discover_falls_back_to_link_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    from trafilatura import feeds as tfeeds

    monkeypatch.setattr(tfeeds, "find_feed_urls", lambda *_a, **_kw: [])

    rows = auto_discover_entries(_PAGE_NO_FEED_HTML, BASE_URL, SOURCE_ID)
    assert len(rows) == 2
    for r in rows:
        assert r["stix_type"] == SCRAPE_STIX_TYPE
        assert r["source_id"] == SOURCE_ID
        assert r["raw_reference"].startswith("https://example.test/")
        assert r["title"]
        assert r["content_hash"]
        assert isinstance(r["observed_at"], datetime)
        assert r["observed_at"].tzinfo is not None
        assert r["visibility"] == "shared"

    links = {r["raw_reference"] for r in rows}
    assert "https://example.test/post-1" in links
    assert "https://example.test/post-2" in links


# ---------------------------------------------------------------------------
# auto_discover_entries - feed-discovery path preferred
# ---------------------------------------------------------------------------


_ATOM_FEED_TWO_ENTRIES = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Feed</title>
  <entry>
    <title>Feed Article Alpha</title>
    <link href="https://example.test/articles/alpha"/>
    <id>https://example.test/articles/alpha</id>
    <updated>2026-04-25T10:00:00Z</updated>
    <summary>summary alpha</summary>
  </entry>
  <entry>
    <title>Feed Article Beta</title>
    <link href="https://example.test/articles/beta"/>
    <id>https://example.test/articles/beta</id>
    <updated>2026-04-25T11:00:00Z</updated>
    <summary>summary beta</summary>
  </entry>
</feed>
"""


def test_auto_discover_uses_feed_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    from trafilatura import feeds as tfeeds

    monkeypatch.setattr(
        tfeeds, "find_feed_urls", lambda *_a, **_kw: ["https://example.test/feed.xml"]
    )
    monkeypatch.setattr(parser_mod, "fetch_html", lambda *a, **kw: _ATOM_FEED_TWO_ENTRIES)

    # Page anchors would yield different rows - assert feed wins.
    rows = auto_discover_entries(_PAGE_NO_FEED_HTML, BASE_URL, SOURCE_ID)
    assert len(rows) == 2
    titles = [r["title"] for r in rows]
    assert "Feed Article Alpha" in titles
    assert "Feed Article Beta" in titles
    links = [r["raw_reference"] for r in rows]
    assert "https://example.test/articles/alpha" in links
    assert "https://example.test/articles/beta" in links


def test_auto_discover_caps_at_max_items(monkeypatch: pytest.MonkeyPatch) -> None:
    # Build a 100-entry Atom feed and assert max_items=10 caps result.
    entries = "".join(
        f"<entry><title>Article {i:03d}</title>"
        f"<link href='https://example.test/a/{i}'/>"
        f"<id>https://example.test/a/{i}</id>"
        f"<updated>2026-04-25T10:00:00Z</updated></entry>"
        for i in range(100)
    )
    big_feed = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        f"<title>Big</title>{entries}</feed>"
    )

    from trafilatura import feeds as tfeeds

    monkeypatch.setattr(
        tfeeds, "find_feed_urls", lambda *_a, **_kw: ["https://example.test/feed.xml"]
    )
    monkeypatch.setattr(parser_mod, "fetch_html", lambda *a, **kw: big_feed)

    rows = auto_discover_entries(_PAGE_NO_FEED_HTML, BASE_URL, SOURCE_ID, max_items=10)
    assert len(rows) == 10


def test_auto_discover_zero_results_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from trafilatura import feeds as tfeeds

    monkeypatch.setattr(tfeeds, "find_feed_urls", lambda *_a, **_kw: [])
    rows = auto_discover_entries("<html></html>", BASE_URL, SOURCE_ID)
    assert rows == []


# ---------------------------------------------------------------------------
# normalise_scrape_entries dispatch routing
# ---------------------------------------------------------------------------


def test_normalise_scrape_entries_routes_auto_to_auto_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = [{"sentinel": True}]
    monkeypatch.setattr(parser_mod, "auto_discover_entries", lambda *a, **kw: sentinel)
    out = normalise_scrape_entries(
        "<html></html>", "https://x.test/", uuid.uuid4(), {"mode": "auto"}
    )
    assert out is sentinel
