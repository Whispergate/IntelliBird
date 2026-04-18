"""tag_mode=any|all filter — plan 06-03 target (MAP-01)."""
from __future__ import annotations

from app.services.events_query import EventsQueryParams, build_events_query, build_fts_query


def _compile(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def _compile_fts(stmt) -> str:
    """For FTS stmts that contain REGCONFIG params, fall back to str(stmt)."""
    return str(stmt)


# ---------------------------------------------------------------------------
# build_events_query tests
# ---------------------------------------------------------------------------

def test_tag_mode_default_uses_contains():
    """Default tag_mode ('all') should use @> (array contains), NOT &&."""
    params = EventsQueryParams(tag=["a", "b"])
    stmt = build_events_query(params, role=None)
    sql = _compile(stmt)
    assert "@>" in sql
    assert "&&" not in sql


def test_tag_mode_any_uses_overlap():
    """tag_mode='any' should use && (array overlap), NOT @>."""
    params = EventsQueryParams(tag=["a", "b"], tag_mode="any")
    stmt = build_events_query(params, role=None)
    sql = _compile(stmt)
    assert "&&" in sql
    assert "@>" not in sql


def test_tag_mode_all_explicit_uses_contains():
    """Explicit tag_mode='all' behaves identically to default — uses @>, not &&."""
    params = EventsQueryParams(tag=["a", "b"], tag_mode="all")
    stmt = build_events_query(params, role=None)
    sql = _compile(stmt)
    assert "@>" in sql
    assert "&&" not in sql


# ---------------------------------------------------------------------------
# build_fts_query tests (same logic, FTS path)
# ---------------------------------------------------------------------------

def test_tag_mode_respected_on_fts_path_default():
    """FTS path with default tag_mode uses @> (array contains)."""
    params = EventsQueryParams(tag=["actor"], tag_mode="all")
    stmt = build_fts_query(params, role=None, q="actor")
    sql = _compile_fts(stmt)
    assert "@>" in sql
    assert "&&" not in sql


def test_tag_mode_respected_on_fts_path_any():
    """FTS path with tag_mode='any' uses && (array overlap)."""
    params = EventsQueryParams(tag=["actor", "c2"], tag_mode="any")
    stmt = build_fts_query(params, role=None, q="actor")
    sql = _compile_fts(stmt)
    assert "&&" in sql
    assert "@>" not in sql


def test_tag_mode_respected_on_fts_path_explicit_all():
    """FTS path with explicit tag_mode='all' uses @>, not &&."""
    params = EventsQueryParams(tag=["actor"], tag_mode="all")
    stmt = build_fts_query(params, role=None, q="actor")
    sql = _compile_fts(stmt)
    assert "@>" in sql
    assert "&&" not in sql
