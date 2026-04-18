"""Tests for X-Dashboard-Role visibility filter — FIL-02 / D-08."""
from __future__ import annotations

from app.services.events_query import EventsQueryParams, build_events_query


def _sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": False})).lower()


def test_visibility_red_filter():
    sql = _sql(build_events_query(EventsQueryParams(), role="red"))
    assert "events.visibility in" in sql
    # red_only and shared present in bound params (compiled SQL shows 'in (...)' placeholders)
    # Check by re-compiling with literal binds:
    sql_lit = str(
        build_events_query(EventsQueryParams(), role="red").compile(
            compile_kwargs={"literal_binds": True}
        )
    ).lower()
    assert "red_only" in sql_lit
    assert "shared" in sql_lit
    assert "blue_only" not in sql_lit


def test_visibility_blue_filter():
    sql_lit = str(
        build_events_query(EventsQueryParams(), role="blue").compile(
            compile_kwargs={"literal_binds": True}
        )
    ).lower()
    assert "blue_only" in sql_lit
    assert "shared" in sql_lit
    assert "red_only" not in sql_lit


def test_visibility_absent_header_no_filter():
    sql_lit = str(
        build_events_query(EventsQueryParams(), role=None).compile(
            compile_kwargs={"literal_binds": True}
        )
    ).lower()
    # The SELECT projects events.visibility as a column — that's expected.
    # The WHERE clause must NOT contain a visibility filter when no role header.
    assert "events.visibility in" not in sql_lit


def test_visibility_unknown_role_no_filter():
    sql_lit = str(
        build_events_query(EventsQueryParams(), role="purple").compile(
            compile_kwargs={"literal_binds": True}
        )
    ).lower()
    assert "events.visibility in" not in sql_lit
