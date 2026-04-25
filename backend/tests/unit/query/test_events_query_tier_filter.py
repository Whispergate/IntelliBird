"""Unit tests for tier-filter WHERE clause in build_events_query.

Plan 15-05 / SCR-05.

These tests compile the SQLAlchemy Select to a SQL string (no DB required) and
assert that score range predicates appear in the WHERE clause.
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa

from app.services.events_query import EventsQueryParams, build_events_query


def _compile(params: EventsQueryParams) -> str:
    """Build a Select and return its compiled SQL string (literal binds)."""
    stmt = build_events_query(params, dashboard_roles=None)
    return str(
        stmt.compile(
            dialect=sa.dialects.postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_tier_filter_S_clause() -> None:
    """tier=['S']: WHERE clause should contain >= 90.0 and <= 100.0."""
    params = EventsQueryParams(tier=["S"])
    sql = _compile(params)
    # TIER_RANGES["S"] = (90.0, 100.0)
    assert "90.0" in sql, f"Expected 90.0 (S tier lower bound) in SQL:\n{sql}"
    assert "100.0" in sql, f"Expected 100.0 (S tier upper bound) in SQL:\n{sql}"


def test_tier_filter_multi_OR_clause() -> None:
    """tier=['S','A']: WHERE clause should include an OR joining S and A ranges."""
    params = EventsQueryParams(tier=["S", "A"])
    sql = _compile(params)
    sql_upper = sql.upper()
    # Both tier ranges must appear.
    # S: 90.0-100.0, A: 75.0-89.99
    assert "90.0" in sql, f"Expected 90.0 (S tier) in SQL:\n{sql}"
    assert "75.0" in sql, f"Expected 75.0 (A tier lower bound) in SQL:\n{sql}"
    # The OR combinator must join the two range clauses.
    assert " OR " in sql_upper, f"Expected OR in tier filter SQL:\n{sql_upper}"


def test_tier_filter_A_bounds() -> None:
    """tier=['A']: WHERE clause should contain >= 75.0 and <= 89.99."""
    params = EventsQueryParams(tier=["A"])
    sql = _compile(params)
    assert "75.0" in sql, f"Expected 75.0 (A tier lower bound) in SQL:\n{sql}"
    assert "89.99" in sql, f"Expected 89.99 (A tier upper bound) in SQL:\n{sql}"


def test_tier_filter_D_bounds() -> None:
    """tier=['D']: WHERE clause should contain >= 0.0 and <= 29.99.

    This also covers the NULL/unscored rows path: COALESCE(score, 0) maps
    unscored rows to 0, which falls in tier D — per RESEARCH.md Pitfall 3.
    """
    params = EventsQueryParams(tier=["D"])
    sql = _compile(params)
    assert "0.0" in sql, f"Expected 0.0 (D tier lower bound) in SQL:\n{sql}"
    assert "29.99" in sql, f"Expected 29.99 (D tier upper bound) in SQL:\n{sql}"


def test_tier_filter_invalid_tier_raises() -> None:
    """tier=['X']: TIER_RANGES lookup raises KeyError for unknown tier label."""
    params = EventsQueryParams(tier=["X"])
    with pytest.raises(KeyError):
        _compile(params)


def test_no_tier_no_score_where() -> None:
    """tier=None: no score-based WHERE clause added to the statement."""
    params = EventsQueryParams(tier=None)
    sql = _compile(params)
    sql_upper = sql.upper()
    # No score range literals should appear.
    assert "90.0" not in sql, f"Unexpected 90.0 (S tier) in default SQL:\n{sql}"
    assert "POWER(" not in sql_upper, (
        f"Unexpected POWER( in default SQL:\n{sql}"
    )
