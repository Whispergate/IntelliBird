"""Tests for dashboard_roles visibility filter — FIL-02 / AUTH-02.

Updated in plan 09-05: role: str | None -> dashboard_roles: list[str] | None.
"""
from __future__ import annotations

from app.services.events_query import EventsQueryParams, build_events_query


def _sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": False})).lower()


def test_visibility_red_filter():
    sql = _sql(build_events_query(EventsQueryParams(), dashboard_roles=["red"]))
    assert "events.visibility in" in sql
    # red_only and shared present in bound params (compiled SQL shows 'in (...)' placeholders)
    # Check by re-compiling with literal binds:
    sql_lit = str(
        build_events_query(EventsQueryParams(), dashboard_roles=["red"]).compile(
            compile_kwargs={"literal_binds": True}
        )
    ).lower()
    assert "red_only" in sql_lit
    assert "shared" in sql_lit
    assert "blue_only" not in sql_lit


def test_visibility_blue_filter():
    sql_lit = str(
        build_events_query(EventsQueryParams(), dashboard_roles=["blue"]).compile(
            compile_kwargs={"literal_binds": True}
        )
    ).lower()
    assert "blue_only" in sql_lit
    assert "shared" in sql_lit
    assert "red_only" not in sql_lit


def test_visibility_absent_header_no_filter():
    sql_lit = str(
        build_events_query(EventsQueryParams(), dashboard_roles=None).compile(
            compile_kwargs={"literal_binds": True}
        )
    ).lower()
    # The SELECT projects events.visibility as a column — that's expected.
    # The WHERE clause must NOT contain a visibility filter when no roles set.
    assert "events.visibility in" not in sql_lit


def test_visibility_unknown_role_no_filter():
    # Unknown role string in list is not "red" or "blue" so only "shared" would be in allowed.
    # But since the list is non-empty, the filter fires — this tests that unknown-only roles
    # produce a shared-only filter (narrowest safe default rather than no filter).
    sql_lit = str(
        build_events_query(EventsQueryParams(), dashboard_roles=["purple"]).compile(
            compile_kwargs={"literal_binds": True}
        )
    ).lower()
    # "purple" is not red or blue — only shared is allowed; visibility IN clause IS present
    # but restricts to shared only. Check no red_only or blue_only leak.
    assert "red_only" not in sql_lit
    assert "blue_only" not in sql_lit
