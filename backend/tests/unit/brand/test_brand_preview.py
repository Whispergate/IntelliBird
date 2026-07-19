"""Unit tests for brand_preview - test-coverage SQL + Redis cache.

Activated by plan 12-03 (was Wave 0 stub in plan 12-00).
Covers H-5 truths:
- Redis cache key shape brand:preview:{project_id}:{term}:{term_type}
- 60s TTL via SETEX
- warning='likely_too_broad' when match rate > 20% of last 1000 events
- percent rounded to 1 decimal place
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.brand_preview import (
    CACHE_TTL_SECONDS,
    SAMPLE_SIZE,
    TOO_BROAD_THRESHOLD,
    _cache_key,
    preview_term,
)
from app.schemas.brand import BrandPreviewResponse


def _mock_session(total: int, hits: int):
    """Build an AsyncSession stub whose .execute() returns a row with {total, hits}."""
    row = MagicMock()
    row.mappings.return_value.one.return_value = {"total": total, "hits": hits}
    session = MagicMock()
    session.execute = AsyncMock(return_value=row)
    return session


def _mock_redis(get_value=None):
    redis = MagicMock()
    redis.get = AsyncMock(return_value=get_value)
    redis.setex = AsyncMock(return_value=True)
    return redis


# ---------------------------------------------------------------------------
# cache key
# ---------------------------------------------------------------------------

def test_cache_key_shape():
    pid = uuid4()
    key = _cache_key(pid, "acme", "keyword")
    assert key == f"brand:preview:{pid}:acme:keyword"


def test_cache_key_constants():
    assert CACHE_TTL_SECONDS == 60
    assert SAMPLE_SIZE == 1000
    assert TOO_BROAD_THRESHOLD == 0.20


# ---------------------------------------------------------------------------
# cache hit / miss
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_hit_returns_cached():
    pid = uuid4()
    cached = BrandPreviewResponse(
        preview_matches=42, percent=4.2, warning=None
    ).model_dump_json()
    redis = _mock_redis(get_value=cached)
    session = _mock_session(total=1000, hits=999)  # should not be consulted

    resp = await preview_term(
        session=session, redis=redis, project_id=pid, term="acme", term_type="keyword"
    )

    assert resp.preview_matches == 42
    assert resp.percent == 4.2
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_cache_miss_runs_sql_and_caches():
    pid = uuid4()
    redis = _mock_redis(get_value=None)
    session = _mock_session(total=1000, hits=50)

    resp = await preview_term(
        session=session, redis=redis, project_id=pid, term="acme", term_type="keyword"
    )

    assert resp.preview_matches == 50
    session.execute.assert_called_once()
    # SETEX called with TTL=60 and serialized response
    redis.setex.assert_called_once()
    call = redis.setex.call_args
    key, ttl, value = call.args
    assert key == f"brand:preview:{pid}:acme:keyword"
    assert ttl == CACHE_TTL_SECONDS
    # value is a JSON string containing preview_matches
    assert "preview_matches" in value


# ---------------------------------------------------------------------------
# warning threshold
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_warning_likely_too_broad_when_gt_20pct():
    pid = uuid4()
    session = _mock_session(total=1000, hits=250)  # 25%
    resp = await preview_term(
        session=session,
        redis=_mock_redis(),
        project_id=pid,
        term="the",
        term_type="keyword",
    )
    assert resp.warning == "likely_too_broad"
    assert resp.percent == 25.0


@pytest.mark.asyncio
async def test_no_warning_when_low_match_rate():
    pid = uuid4()
    session = _mock_session(total=1000, hits=50)  # 5%
    resp = await preview_term(
        session=session,
        redis=_mock_redis(),
        project_id=pid,
        term="acmexyz",
        term_type="keyword",
    )
    assert resp.warning is None
    assert resp.percent == 5.0


@pytest.mark.asyncio
async def test_percent_rounded_to_one_decimal():
    pid = uuid4()
    session = _mock_session(total=1000, hits=234)  # 23.4%
    resp = await preview_term(
        session=session,
        redis=_mock_redis(),
        project_id=pid,
        term="x",
        term_type="keyword",
    )
    assert resp.percent == 23.4


@pytest.mark.asyncio
async def test_empty_events_table_returns_zero_no_warning():
    """Zero total events → 0% match, no warning (avoid div-by-zero)."""
    pid = uuid4()
    session = _mock_session(total=0, hits=0)
    resp = await preview_term(
        session=session,
        redis=_mock_redis(),
        project_id=pid,
        term="acme",
        term_type="keyword",
    )
    assert resp.preview_matches == 0
    assert resp.percent == 0.0
    assert resp.warning is None


@pytest.mark.asyncio
async def test_exactly_20_percent_no_warning():
    """Threshold is strictly > 20% - exactly 20% is not 'likely_too_broad'."""
    pid = uuid4()
    session = _mock_session(total=1000, hits=200)  # exactly 20%
    resp = await preview_term(
        session=session,
        redis=_mock_redis(),
        project_id=pid,
        term="x",
        term_type="keyword",
    )
    assert resp.warning is None
