"""Unit tests for bbot_runner semaphore functions - EASM-09.

Plan: 11-04a

Tests use mocked Redis - no live Redis, no live DB.
"""
from __future__ import annotations

from unittest.mock import MagicMock


import os
os.environ.setdefault("SECRET_KEY", "a" * 32)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SIGNING_KEY", "b" * 32)

from app.services.bbot_runner import (  # noqa: E402
    _SEMAPHORE_KEY,
    acquire_semaphore,
    heal_semaphore_from_db,
    release_semaphore,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _make_redis(incr_return_value: int) -> MagicMock:
    r = MagicMock()
    r.incr.return_value = incr_return_value
    r.decr.return_value = incr_return_value - 1
    r.set.return_value = True
    return r


# ===========================================================================
# acquire_semaphore
# ===========================================================================


def test_acquire_under_limit_returns_true():
    """INCR → 1; limit=2 → True (slot available)."""
    r = _make_redis(incr_return_value=1)
    result = acquire_semaphore(r, limit=2)
    assert result is True
    r.incr.assert_called_once_with(_SEMAPHORE_KEY)
    r.decr.assert_not_called()


def test_acquire_at_limit_returns_true():
    """INCR → 2; limit=2 → True (exactly at limit, slot accepted)."""
    r = _make_redis(incr_return_value=2)
    result = acquire_semaphore(r, limit=2)
    assert result is True
    r.incr.assert_called_once_with(_SEMAPHORE_KEY)
    r.decr.assert_not_called()


def test_acquire_over_limit_decrs_and_returns_false():
    """INCR → 3; limit=2 → DECR called, False returned."""
    r = _make_redis(incr_return_value=3)
    result = acquire_semaphore(r, limit=2)
    assert result is False
    r.incr.assert_called_once_with(_SEMAPHORE_KEY)
    r.decr.assert_called_once_with(_SEMAPHORE_KEY)


def test_acquire_limit_1_allows_first_rejects_second():
    """Single-slot semaphore: first acquire succeeds, second is rejected."""
    r_first = _make_redis(incr_return_value=1)
    r_second = _make_redis(incr_return_value=2)

    assert acquire_semaphore(r_first, limit=1) is True
    assert acquire_semaphore(r_second, limit=1) is False
    r_second.decr.assert_called_once_with(_SEMAPHORE_KEY)


# ===========================================================================
# release_semaphore
# ===========================================================================


def test_release_decrs_unconditionally():
    """release_semaphore must call DECR on the semaphore key."""
    r = MagicMock()
    release_semaphore(r)
    r.decr.assert_called_once_with(_SEMAPHORE_KEY)


def test_release_does_not_call_incr():
    """release_semaphore must not INCR."""
    r = MagicMock()
    release_semaphore(r)
    r.incr.assert_not_called()


# ===========================================================================
# heal_semaphore_from_db
# ===========================================================================


def test_heal_sets_count_from_db():
    """Startup heal: SET semaphore to SELECT count(*) WHERE status='running' → 3."""
    db_sync = MagicMock()
    db_sync.execute.return_value.scalar.return_value = 3
    r = MagicMock()

    result = heal_semaphore_from_db(db_sync, r)

    assert result == 3
    r.set.assert_called_once_with(_SEMAPHORE_KEY, 3)


def test_heal_with_no_running_scans_sets_zero():
    """When scalar() returns None (0 rows), heal must SET key to 0."""
    db_sync = MagicMock()
    db_sync.execute.return_value.scalar.return_value = None
    r = MagicMock()

    result = heal_semaphore_from_db(db_sync, r)

    assert result == 0
    r.set.assert_called_once_with(_SEMAPHORE_KEY, 0)


def test_heal_returns_count_not_redis_return():
    """heal_semaphore_from_db returns the DB count (not the Redis SET return value)."""
    db_sync = MagicMock()
    db_sync.execute.return_value.scalar.return_value = 7
    r = MagicMock()
    r.set.return_value = "OK"  # Redis returns OK string

    result = heal_semaphore_from_db(db_sync, r)
    assert result == 7


# ===========================================================================
# Semaphore key constant
# ===========================================================================


def test_semaphore_key_is_expected_string():
    """_SEMAPHORE_KEY must be 'bbot:concurrent_scans' per CONTEXT.md."""
    assert _SEMAPHORE_KEY == "bbot:concurrent_scans"
