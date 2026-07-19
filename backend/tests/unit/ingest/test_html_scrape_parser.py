"""Unit tests for app.ingest.html_scrape_parser - quick task 260425-ovt.

These tests pin the canonical scrape_config contract, the @attr selector syntax,
the urljoin behaviour, the max_items cap, the date fallback, and the dedup
content_hash being identical to the RSS hasher (so re-polling the same URL
dedups via the existing UNIQUE (source_id, content_hash, observed_at) index).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.ingest.dedup import rss_content_hash
from app.ingest.html_scrape_parser import (
    MAX_ITEMS_HARD_CAP,
    SCRAPE_STIX_TYPE,
    normalise_scrape_entries,
    validate_scrape_config,
)

FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "html_scrape_checkpoint.html"
)
BASE_URL = "https://research.checkpoint.com/"
SOURCE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

DEFAULT_CFG: dict = {
    "item_selector": "article.post",
    "title_selector": "h2 a",
    "link_selector": "h2 a@href",
    "date_selector": "time@datetime",
    "summary_selector": ".excerpt",
}


def _html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_extracts_items_from_fixture() -> None:
    rows = normalise_scrape_entries(_html(), BASE_URL, SOURCE_ID, DEFAULT_CFG)
    assert len(rows) >= 3
    for r in rows:
        assert r["title"]
        assert r["raw_reference"].startswith("https://")
        assert r["stix_type"] == SCRAPE_STIX_TYPE
        assert isinstance(r["observed_at"], datetime)
        assert r["observed_at"].tzinfo is not None
        assert r["content_hash"]
        assert r["source_id"] == SOURCE_ID
        assert r["visibility"] == "shared"


def test_resolves_relative_links() -> None:
    rows = normalise_scrape_entries(_html(), BASE_URL, SOURCE_ID, DEFAULT_CFG)
    links = [r["raw_reference"] for r in rows]
    assert any(link == "https://research.checkpoint.com/2026/04/post-one" for link in links)
    assert all(link.startswith("https://research.checkpoint.com/") for link in links)


def test_attribute_selector_syntax() -> None:
    # Plain selector → text. Attribute selector → attr value.
    rows_text = normalise_scrape_entries(
        _html(),
        BASE_URL,
        SOURCE_ID,
        {**DEFAULT_CFG, "title_selector": "h2 a"},
    )
    assert rows_text[0]["title"].startswith("Threat Brief One")

    rows_attr = normalise_scrape_entries(
        _html(),
        BASE_URL,
        SOURCE_ID,
        {**DEFAULT_CFG, "link_selector": "h2 a@href"},
    )
    assert rows_attr[0]["raw_reference"].endswith("/2026/04/post-one")


def test_missing_required_selectors_raises() -> None:
    bad = {"item_selector": "article.post"}
    with pytest.raises(ValueError, match="scrape_config missing required key"):
        validate_scrape_config(bad)


def test_max_items_cap() -> None:
    # max_items=2 → 2 rows
    rows2 = normalise_scrape_entries(
        _html(), BASE_URL, SOURCE_ID, {**DEFAULT_CFG, "max_items": 2}
    )
    assert len(rows2) == 2

    # missing max_items → default 50 (fixture has 5 valid items + 1 empty skipped)
    rows_default = normalise_scrape_entries(_html(), BASE_URL, SOURCE_ID, DEFAULT_CFG)
    assert len(rows_default) == 5

    # values > MAX_ITEMS_HARD_CAP are clamped
    rows_clamped = normalise_scrape_entries(
        _html(), BASE_URL, SOURCE_ID, {**DEFAULT_CFG, "max_items": 99999}
    )
    assert len(rows_clamped) <= MAX_ITEMS_HARD_CAP


def test_date_fallback() -> None:
    cfg_no_date = {k: v for k, v in DEFAULT_CFG.items() if k != "date_selector"}
    before = datetime.now(timezone.utc)
    rows = normalise_scrape_entries(_html(), BASE_URL, SOURCE_ID, cfg_no_date)
    after = datetime.now(timezone.utc)
    for r in rows:
        assert r["observed_at"].tzinfo is not None
        # Within the bracket window (allow tiny clock skew margin).
        assert before.timestamp() - 1 <= r["observed_at"].timestamp() <= after.timestamp() + 1


def test_skips_items_missing_title_or_link() -> None:
    # Fixture's 6th article has empty href + empty title → must be filtered out.
    rows = normalise_scrape_entries(_html(), BASE_URL, SOURCE_ID, DEFAULT_CFG)
    assert len(rows) == 5
    for r in rows:
        assert r["title"]
        assert r["raw_reference"]


def test_content_hash_uses_rss_hasher() -> None:
    rows = normalise_scrape_entries(_html(), BASE_URL, SOURCE_ID, DEFAULT_CFG)
    r = rows[0]
    expected = rss_content_hash(str(SOURCE_ID), r["raw_reference"], r["title"])
    assert r["content_hash"] == expected
