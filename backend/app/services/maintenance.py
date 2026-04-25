"""Maintenance window helper (Phase 16 H-7).

Single source of truth: monitoring dispatchers call is_maintenance_active(session)
BEFORE emitting any canonical event. No daemon — past windows auto-expire because
`now() BETWEEN start_at AND end_at` simply stops matching them.

Index: ix_mw_range on (start_at, end_at) — created in migration 016 — keeps this
sub-millisecond regardless of history size.

Usage:
    from app.services.maintenance import is_maintenance_active

    if is_maintenance_active(session):
        return  # suppress alert during planned maintenance
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def is_maintenance_active(session: Session) -> bool:
    """True iff at least one maintenance_windows row covers now().

    Executes a single indexed range query:
        SELECT 1 FROM maintenance_windows WHERE now() BETWEEN start_at AND end_at LIMIT 1

    Sub-millisecond against the ix_mw_range (start_at, end_at) index created
    in migration 016. Past windows auto-expire — no cleanup daemon needed.

    Args:
        session: Synchronous SQLAlchemy Session. Monitoring scheduler jobs use
            sync psycopg2 sessions (APScheduler is sync; mixing asyncio is an
            anti-pattern per 16-RESEARCH.md). If an async context needs this,
            add is_maintenance_active_async(async_session) in a later plan.

    Returns:
        True if a maintenance window is currently active, False otherwise.
    """
    result = session.execute(
        text(
            "SELECT 1 FROM maintenance_windows "
            "WHERE now() BETWEEN start_at AND end_at "
            "LIMIT 1"
        )
    ).fetchone()
    return result is not None
