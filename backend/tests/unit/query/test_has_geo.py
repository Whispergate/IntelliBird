"""has_geo filter parameter --03 target (MAP-01)."""
from __future__ import annotations


from app.services.events_query import EventsQueryParams, build_events_query, build_fts_query


def _compile(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def _compile_fts(stmt) -> str:
    """For FTS stmts that contain REGCONFIG params, fall back to str(stmt)."""
    return str(stmt)


def test_has_geo_false_emits_no_geo_predicate():
    """When has_geo=False (default), the SQL must NOT contain geo_lat IS NOT NULL."""
    params = EventsQueryParams(has_geo=False)
    stmt = build_events_query(params, dashboard_roles=None)
    sql = _compile(stmt)
    assert "geo_lat IS NOT NULL" not in sql


def test_has_geo_true_emits_both_geo_predicates():
    """When has_geo=True, the SQL must contain both geo_lat IS NOT NULL and geo_lon IS NOT NULL."""
    params = EventsQueryParams(has_geo=True)
    stmt = build_events_query(params, dashboard_roles=None)
    sql = _compile(stmt)
    assert "geo_lat IS NOT NULL" in sql
    assert "geo_lon IS NOT NULL" in sql


def test_has_geo_true_on_fts_path():
    """build_fts_query with has_geo=True also emits both geo predicates."""
    params = EventsQueryParams(has_geo=True)
    stmt = build_fts_query(params, dashboard_roles=None, q="exploit")
    sql = _compile_fts(stmt)
    assert "geo_lat IS NOT NULL" in sql
    assert "geo_lon IS NOT NULL" in sql
