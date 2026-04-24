"""Unit tests for brand_synth — canonical event dict + STIX 2.1 Indicator SDO.

Activated by plan 12-03 (was Wave 0 stub in plan 12-00).
Covers BRP-05 truths:
- content_hash formula
- source_type='brand-monitor', stix_type='indicator'
- title/description/tags shape
- STIX 2.1 Indicator SDO with allow_custom + x_intellibird_* properties
- pattern branching: domain-name vs x_intellibird_brand_match_keyword
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.services.brand_synth import (
    _content_hash,
    build_event_dict,
    build_stix_indicator,
)


def _make_match(**overrides):
    base = {
        "id": uuid4(),
        "project_id": uuid4(),
        "brand_term_id": uuid4(),
        "matched_value": "evil-acme.com",
        "match_source": "dnstwist",
        "severity": "high",
        "first_seen": datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


def _make_term(**overrides):
    base = {
        "id": uuid4(),
        "value": "Acme",
        "term_type": "keyword",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# content_hash
# ---------------------------------------------------------------------------

def test_content_hash_formula():
    match = _make_match()
    term = _make_term(id=match["brand_term_id"])
    # Formula: sha256(str(project_id) + 'brand-match' + str(brand_term_id) + matched_value)
    expected = hashlib.sha256(
        (
            str(match["project_id"])
            + "brand-match"
            + str(match["brand_term_id"])
            + match["matched_value"]
        ).encode()
    ).hexdigest()
    result = build_event_dict(match=match, term=term)
    assert result["content_hash"] == expected
    assert len(result["content_hash"]) == 64


def test_content_hash_helper_is_hex_64():
    h = _content_hash("p", "t", "v")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# canonical event dict shape
# ---------------------------------------------------------------------------

def test_source_type_key_not_emitted():
    """Plan 12-12 / BRP-05 drift fix: events table has no source_type column,
    so build_event_dict must NOT emit the key. Brand provenance is carried
    entirely by the tags array (brand-match, brand-match:<severity>,
    brand-match:<source>, project:<id>)."""
    result = build_event_dict(match=_make_match(), term=_make_term())
    assert "source_type" not in result


def test_stix_type_is_indicator():
    result = build_event_dict(match=_make_match(), term=_make_term())
    assert result["stix_type"] == "indicator"


def test_title_format():
    term = _make_term(value="Acme")
    match = _make_match(severity="high")
    result = build_event_dict(match=match, term=term)
    assert result["title"] == "Brand match: Acme (high)"


def test_description_multiline():
    match = _make_match()
    term = _make_term()
    result = build_event_dict(match=match, term=term)
    desc = result["description"]
    assert "Matched value:" in desc
    assert "Source:" in desc
    assert "Term type:" in desc
    assert "First seen:" in desc
    assert "Dashboard:" in desc


def test_tags_include_required():
    match = _make_match(match_source="dnstwist", severity="high")
    term = _make_term()
    result = build_event_dict(match=match, term=term)
    tags = result["tags"]
    assert "brand-match" in tags
    assert "brand-match:high" in tags
    assert f"brand-match:{match['match_source']}" in tags
    assert f"project:{match['project_id']}" in tags


def test_observed_at_uses_now():
    result = build_event_dict(match=_make_match(), term=_make_term())
    now = datetime.now(timezone.utc)
    assert abs((result["observed_at"] - now).total_seconds()) < 5


# ---------------------------------------------------------------------------
# STIX 2.1 pattern branching
# ---------------------------------------------------------------------------

def test_stix_pattern_domain_type():
    match = _make_match(matched_value="evil-acme.com")
    term = _make_term(term_type="domain", value="acme.com")
    result = build_event_dict(match=match, term=term)
    assert result["raw_stix"]["pattern"] == "[domain-name:value = 'evil-acme.com']"


def test_stix_pattern_keyword_type():
    match = _make_match(matched_value="Acme Corp")
    term = _make_term(term_type="keyword", value="Acme")
    result = build_event_dict(match=match, term=term)
    assert (
        result["raw_stix"]["pattern"]
        == "[x_intellibird_brand_match_keyword:value = 'Acme Corp']"
    )


def test_stix_pattern_product_uses_custom_keyword():
    match = _make_match(matched_value="FooWidget Pro")
    term = _make_term(term_type="product", value="FooWidget")
    result = build_event_dict(match=match, term=term)
    assert (
        result["raw_stix"]["pattern"]
        == "[x_intellibird_brand_match_keyword:value = 'FooWidget Pro']"
    )


def test_stix_pattern_person_uses_custom_keyword():
    match = _make_match(matched_value="Jane Doe")
    term = _make_term(term_type="person", value="Jane Doe")
    result = build_event_dict(match=match, term=term)
    assert (
        result["raw_stix"]["pattern"]
        == "[x_intellibird_brand_match_keyword:value = 'Jane Doe']"
    )


# ---------------------------------------------------------------------------
# STIX 2.1 Indicator custom properties
# ---------------------------------------------------------------------------

def test_stix_indicator_allow_custom_properties():
    match = _make_match()
    term = _make_term()
    result = build_event_dict(match=match, term=term)
    raw = result["raw_stix"]
    assert raw["x_intellibird_brand_match_id"] == str(match["id"])
    assert raw["x_intellibird_project_id"] == str(match["project_id"])
    assert raw["x_intellibird_term_id"] == str(term["id"])
    assert raw["type"] == "indicator"
    assert raw["pattern_type"] == "stix"


def test_build_stix_indicator_standalone():
    """build_stix_indicator is callable directly with keyword-only args."""
    match_id = uuid4()
    project_id = uuid4()
    term_id = uuid4()
    indicator = build_stix_indicator(
        match_id=match_id,
        project_id=project_id,
        term_id=term_id,
        term_type="domain",
        term_value="acme.com",
        matched_value="evil-acme.com",
        severity="high",
    )
    assert indicator["type"] == "indicator"
    assert indicator["pattern"] == "[domain-name:value = 'evil-acme.com']"
    assert indicator["x_intellibird_brand_match_id"] == str(match_id)


def test_stix_id_present_in_event_dict():
    """events table needs stix_id; raw_stix['id'] is propagated."""
    result = build_event_dict(match=_make_match(), term=_make_term())
    assert result["stix_id"] == result["raw_stix"]["id"]
    assert result["stix_id"].startswith("indicator--")
