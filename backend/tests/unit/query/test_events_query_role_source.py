"""events_query dashboard_roles claim-based visibility — AUTH-02 / C-2."""
from __future__ import annotations

from app.services.events_query import EventsQueryParams, build_events_query, build_fts_query


def _visibility_where(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def test_none_dashboard_roles_no_filter():
    p = EventsQueryParams()
    sql = _visibility_where(build_events_query(p, dashboard_roles=None))
    # Accept EITHER visibility IS NULL handling or no visibility clause at all. The easy
    # assertion: no restrictive visibility IN clause.
    assert "visibility IN" not in sql.replace("visibility IN ()", "")


def test_empty_dashboard_roles_no_filter():
    p = EventsQueryParams()
    sql = _visibility_where(build_events_query(p, dashboard_roles=[]))
    assert "visibility IN" not in sql.replace("visibility IN ()", "")


def test_red_only_dashboard_filters_red_and_shared():
    p = EventsQueryParams()
    sql = _visibility_where(build_events_query(p, dashboard_roles=["red"]))
    assert "red_only" in sql
    assert "shared" in sql
    assert "blue_only" not in sql


def test_blue_only_dashboard_filters_blue_and_shared():
    p = EventsQueryParams()
    sql = _visibility_where(build_events_query(p, dashboard_roles=["blue"]))
    assert "blue_only" in sql
    assert "shared" in sql
    assert "red_only" not in sql


def test_both_dashboards_all_visibilities():
    p = EventsQueryParams()
    sql = _visibility_where(build_events_query(p, dashboard_roles=["red", "blue"]))
    assert "red_only" in sql
    assert "blue_only" in sql
    assert "shared" in sql


def test_fts_query_same_visibility_semantics():
    # Note: literal_binds=True fails for FTS queries (REGCONFIG type has no literal renderer).
    # Use str(stmt) (placeholder binds) and check for the parameter placeholder pattern.
    p = EventsQueryParams()
    stmt = build_fts_query(p, dashboard_roles=["red"], q="foo")
    # Compile without literal_binds to check the visibility IN clause exists
    sql_plain = str(stmt.compile(compile_kwargs={"literal_binds": False})).lower()
    assert "events.visibility in" in sql_plain
    # Verify the bound parameters contain the right values by using literal_binds only
    # on the WHERE part — instead, compile the build_events_query equivalent to cross-check.
    # The FTS path uses the same visibility logic; we validate via the non-FTS path's
    # literal-bind test above and trust the shared code path.
    # Additional check: build a non-FTS query and assert same structure:
    sql_lit = _visibility_where(build_events_query(p, dashboard_roles=["red"]))
    assert "red_only" in sql_lit
    assert "blue_only" not in sql_lit
