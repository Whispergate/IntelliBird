"""Tests for FTS query builder — FIL-05."""
from __future__ import annotations

import uuid

import pytest

from app.services.events_query import (
    EventsQueryParams,
    build_fts_query,
)


def _sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": False})).lower()


def test_plainto_tsquery_used_not_to_tsquery():
    stmt = build_fts_query(EventsQueryParams(), role=None, q="apt28")
    sql = _sql(stmt)
    assert "plainto_tsquery" in sql
    assert "to_tsquery('english'" not in sql


def test_ts_rank_cd_used_for_ranking():
    stmt = build_fts_query(EventsQueryParams(), role=None, q="apt28")
    sql = _sql(stmt)
    assert "ts_rank_cd" in sql


def test_search_tsv_match_operator():
    stmt = build_fts_query(EventsQueryParams(), role=None, q="apt28")
    sql = _sql(stmt)
    assert "search_tsv @@" in sql


def test_fts_sort_override_rank_desc_then_observed_at_desc():
    stmt = build_fts_query(EventsQueryParams(), role=None, q="apt28")
    sql = _sql(stmt)
    order_clause = sql.split("order by", 1)[-1]
    # rank label appears first, observed_at second
    assert "rank" in order_clause
    assert order_clause.index("rank") < order_clause.index("observed_at")


def test_empty_free_text_raises():
    with pytest.raises(ValueError):
        build_fts_query(EventsQueryParams(), role=None, q="")
    with pytest.raises(ValueError):
        build_fts_query(EventsQueryParams(), role=None, q="   ")


def test_fts_path_respects_filters_and_visibility():
    sid = uuid.uuid4()
    stmt = build_fts_query(
        EventsQueryParams(source=[sid], tag=["apt28"]),
        role="red",
        q="phishing",
    )
    sql = _sql(stmt)
    assert "events.source_id in" in sql
    assert "coalesce(events.tags" in sql
    assert "events.visibility in" in sql
