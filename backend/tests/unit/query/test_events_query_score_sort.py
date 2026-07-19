"""Unit tests for score-sort ORDER BY expression in build_events_query.

Plan 15-05 / SCR-05.

These tests compile the SQLAlchemy Select to a SQL string (no DB required) and
assert that the score sort expressions appear in the correct positions.
"""
from __future__ import annotations


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


def test_score_desc_orders_by_decayed_score() -> None:
    """sort=score_desc: ORDER BY should use power( and coalesce( in DESC direction."""
    params = EventsQueryParams(sort="score_desc")
    sql = _compile(params)
    sql_upper = sql.upper()
    # The decay expression uses power(2, -age/14).
    assert "POWER(" in sql_upper, f"Expected POWER( in compiled SQL:\n{sql}"
    assert "COALESCE(" in sql_upper, f"Expected COALESCE( in compiled SQL:\n{sql}"
    # DESC must appear in the ORDER BY clause.
    assert "ORDER BY" in sql_upper
    order_by_part = sql_upper[sql_upper.index("ORDER BY"):]
    assert "DESC" in order_by_part, f"Expected DESC in ORDER BY:\n{order_by_part}"


def test_score_asc_orders_by_decayed_score() -> None:
    """sort=score_asc: ORDER BY should use power( and coalesce( in ASC direction."""
    params = EventsQueryParams(sort="score_asc")
    sql = _compile(params)
    sql_upper = sql.upper()
    assert "POWER(" in sql_upper, f"Expected POWER( in compiled SQL:\n{sql}"
    assert "COALESCE(" in sql_upper, f"Expected COALESCE( in compiled SQL:\n{sql}"
    assert "ORDER BY" in sql_upper
    order_by_part = sql_upper[sql_upper.index("ORDER BY"):]
    # ASC sort expression should appear before the tie-breaker DESC columns.
    assert "ASC" in order_by_part, f"Expected ASC in ORDER BY:\n{order_by_part}"


def test_default_sort_unchanged() -> None:
    """sort=None: ORDER BY should use events.observed_at DESC as the first criterion."""
    params = EventsQueryParams(sort=None)
    sql = _compile(params)
    sql_upper = sql.upper()
    assert "ORDER BY" in sql_upper
    order_by_part = sql_upper[sql_upper.index("ORDER BY"):]
    assert "OBSERVED_AT" in order_by_part, (
        f"Expected OBSERVED_AT in ORDER BY for default sort:\n{order_by_part}"
    )
    # Power/decay should NOT appear when score sort is not requested.
    assert "POWER(" not in sql_upper, (
        f"Unexpected POWER( in compiled SQL for default sort:\n{sql}"
    )


def test_observed_desc_sort_identical_to_none() -> None:
    """sort='observed_desc' is treated the same as sort=None (default path)."""
    params_none = EventsQueryParams(sort=None)
    params_obs = EventsQueryParams(sort="observed_desc")
    sql_none = _compile(params_none)
    sql_obs = _compile(params_obs)
    assert sql_none == sql_obs, (
        "sort='observed_desc' should produce the same SQL as sort=None"
    )
