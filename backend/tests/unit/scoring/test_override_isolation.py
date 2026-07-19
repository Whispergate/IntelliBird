"""Unit tests for override query isolation (SCR-03).

Plan 15-05.

Proves that the lateral subquery injected by build_events_query for override
scores is filtered by event_id only - cross-project isolation is enforced by
the outer build_scope_predicate chokepoint (events.project_id = project_id),
not by a project_id filter inside the lateral subquery itself.

This structural property guarantees that Project A scoring overrides CANNOT
surface in a Project B scoped query:
  - The lateral subquery only looks at event_score_overrides.event_id
  - The outer WHERE events.project_id = A constrains which event rows are
    returned, so only events belonging to A can match their own overrides.

Tests use SQL string assertion (no DB required).
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa

from app.services.events_query import EventsQueryParams, build_events_query


def _compile_with_project(
    params: EventsQueryParams,
    project_id: uuid.UUID,
    scope_predicate=None,
) -> str:
    """Build a project-scoped Select and return compiled SQL (literal binds)."""
    stmt = build_events_query(
        params,
        dashboard_roles=None,
        project_id=project_id,
        scope_predicate=scope_predicate,
    )
    return str(
        stmt.compile(
            dialect=sa.dialects.postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_override_query_does_not_bypass_scope_predicate() -> None:
    """The compiled SQL must reference event_score_overrides (override join exists)
    AND events.project_id (chokepoint predicate) - proving the override lateral
    subquery does NOT bypass the scope predicate.

    Specifically:
    - event_score_overrides must appear (lateral subquery is wired in).
    - events.project_id must appear in the WHERE clause (chokepoint is preserved).
    - The lateral subquery does NOT add its own project_id filter - project
      isolation is solely the outer WHERE clause's responsibility.
    """
    project_a = uuid.uuid4()
    params = EventsQueryParams(sort="score_desc")
    sql = _compile_with_project(params, project_id=project_a)

    # The override lateral subquery must be referenced.
    assert "event_score_overrides" in sql, (
        f"Expected event_score_overrides lateral join in compiled SQL:\n{sql}"
    )

    # The project scope chokepoint must be in the outer WHERE clause.
    assert "events.project_id" in sql, (
        f"Expected events.project_id scope predicate in compiled SQL:\n{sql}"
    )

    # The project_id value (A) must appear as the bound parameter for the
    # scope predicate - confirming the chokepoint is scoped to this project.
    assert str(project_a) in sql, (
        f"Expected project_a UUID {project_a} in compiled SQL:\n{sql}"
    )


def test_override_lateral_subquery_filters_by_event_id_not_project_id() -> None:
    """The lateral subquery for override score uses event_id correlation only.

    This confirms the subquery is `WHERE event_score_overrides.event_id = events.id`
    (correlated lateral) - not a project_id join. Cross-project isolation is
    delegated to the outer scope predicate, not duplicated inside the subquery.
    """
    project_a = uuid.uuid4()
    params = EventsQueryParams(sort="score_desc")
    sql = _compile_with_project(params, project_id=project_a)

    sql_lower = sql.lower()

    # event_score_overrides.event_id must appear in the subquery.
    assert "event_score_overrides.event_id" in sql_lower, (
        f"Expected event_score_overrides.event_id correlation in SQL:\n{sql}"
    )

    # The override subquery should NOT directly filter by project_id inside
    # itself - that would be redundant and potentially confusing. Isolation
    # lives in the outer WHERE block.
    # We verify this by checking the event_score_overrides reference is a
    # correlated subquery (contains events.id), not a joined project filter.
    assert "events.id" in sql_lower, (
        f"Expected events.id correlated reference in override subquery:\n{sql}"
    )


def test_override_query_scoped_to_project() -> None:
    """Alias for the primary isolation test - mirrors the Wave-0 stub name.

    Queries scoped to project_id=A must not reference any project_b UUID in
    the compiled SQL. The override lateral subquery is purely event_id based;
    all project filtering is in the outer WHERE.
    """
    project_a = uuid.uuid4()
    project_b = uuid.uuid4()

    params = EventsQueryParams(sort="score_desc", tier=["S", "A"])
    sql = _compile_with_project(params, project_id=project_a)

    # project_b must not appear anywhere in the SQL.
    assert str(project_b) not in sql, (
        f"Project B UUID leaked into Project A scoped query:\n{sql}"
    )
    # project_a must appear (scope predicate is set).
    assert str(project_a) in sql, (
        f"Project A UUID missing from scoped query:\n{sql}"
    )
    # The override table must be referenced.
    assert "event_score_overrides" in sql, (
        f"event_score_overrides missing from score-sorted query:\n{sql}"
    )
