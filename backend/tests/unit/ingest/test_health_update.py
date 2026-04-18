"""Exhaustive coverage of update_source_health — D-33 + VALID_STATUSES.

Phase 2 Wave 0 stub for 02-07. Complements test_canonical_mapper.py's
spot-checks with full enum + success/failure matrix coverage.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from app.ingest.normalise import VALID_STATUSES, update_source_health


def test_valid_statuses_constant_is_exactly_five() -> None:
    assert VALID_STATUSES == frozenset({
        "ok", "rate_limited", "http_error", "network_error", "parse_error",
    })


@pytest.mark.parametrize("status", sorted(VALID_STATUSES))
def test_all_valid_statuses_accepted_with_succeeded_true(status: str) -> None:
    session = MagicMock()
    update_source_health(session, uuid.uuid4(), status=status, succeeded=True)
    assert session.execute.called
    stmt = session.execute.call_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    # literal status string present
    assert f"'{status}'" in compiled
    # consecutive_failures reset to 0
    flat = compiled.replace(" ", "")
    assert "consecutive_failures=0" in flat


@pytest.mark.parametrize("status", sorted(VALID_STATUSES))
def test_all_valid_statuses_accepted_with_succeeded_false(status: str) -> None:
    session = MagicMock()
    update_source_health(session, uuid.uuid4(), status=status, succeeded=False)
    stmt = session.execute.call_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert f"'{status}'" in compiled
    # self-increment expression present (whitespace-tolerant check, handles parens)
    flat = compiled.replace(" ", "").replace("(", "").replace(")", "")
    assert (
        "consecutive_failures=sources.consecutive_failures+1" in flat
        or "consecutive_failures=consecutive_failures+1" in flat
    )


def test_ok_with_succeeded_false_is_nonsensical_but_allowed() -> None:
    """API does not enforce semantic consistency — only the enum."""
    session = MagicMock()
    update_source_health(session, uuid.uuid4(), status="ok", succeeded=False)
    stmt = session.execute.call_args[0][0]
    compiled = (
        str(stmt.compile(compile_kwargs={"literal_binds": True}))
        .replace(" ", "").replace("(", "").replace(")", "")
    )
    assert (
        "consecutive_failures=sources.consecutive_failures+1" in compiled
        or "consecutive_failures=consecutive_failures+1" in compiled
    )


@pytest.mark.parametrize("bogus", [
    "", "OK", "fail", "Rate_Limited", "http-error", "ok ", "RATE_LIMITED",
])
def test_rejects_invalid_status(bogus: str) -> None:
    session = MagicMock()
    with pytest.raises(ValueError, match="invalid status"):
        update_source_health(session, uuid.uuid4(), status=bogus, succeeded=True)


def test_last_polled_at_set_to_now() -> None:
    session = MagicMock()
    update_source_health(session, uuid.uuid4(), status="ok", succeeded=True)
    stmt = session.execute.call_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "now()" in compiled.lower()


def test_where_clause_targets_source_id() -> None:
    session = MagicMock()
    sid = uuid.uuid4()
    update_source_health(session, sid, status="ok", succeeded=True)
    stmt = session.execute.call_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "sources.id" in compiled
    # Postgres UUID literals may be rendered with or without dashes
    sid_str = str(sid)
    assert sid_str in compiled or sid_str.replace("-", "") in compiled


def test_no_cursor_column_touched() -> None:
    """Health update MUST NOT touch last_cursor — cursor advance is a
    separate helper (per plans 02-04 and 02-06).
    """
    session = MagicMock()
    update_source_health(session, uuid.uuid4(), status="ok", succeeded=True)
    stmt = session.execute.call_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True})).lower()
    assert "last_cursor" not in compiled


def test_does_not_commit() -> None:
    """Caller owns the transaction boundary — update_source_health only
    executes the UPDATE statement.
    """
    session = MagicMock()
    update_source_health(session, uuid.uuid4(), status="ok", succeeded=True)
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
