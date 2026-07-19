"""Redis-backed failed-login lockout counter - AUTH-04 / M-7.

Keys (TTL in seconds):
  login:fails:{username}   600   (10 min window)
  login:locked:{username}  1800  (30 min lockout once 5 fails accumulate)

Lock threshold and TTLs pinned per CONTEXT.md.

Dummy-username attempts go through the same counter path (PITFALL 7 mitigation) -
callers do NOT gate record_failure on "user exists" lookups.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

FAILS_TTL_SECONDS: int = 600
LOCKOUT_TTL_SECONDS: int = 1800
FAILS_THRESHOLD: int = 5

if TYPE_CHECKING:
    from redis.asyncio import Redis


def _fails_key(username: str) -> str:
    return f"login:fails:{username}"


def _locked_key(username: str) -> str:
    return f"login:locked:{username}"


async def is_locked(redis: "Redis", username: str) -> tuple[bool, int]:
    """Return (locked, retry_after_seconds). retry_after is 0 when not locked."""
    ttl = await redis.ttl(_locked_key(username))
    if ttl is None or ttl < 0:
        # Redis TTL returns -2 for missing key, -1 for no-TTL; both mean "not locked"
        return False, 0
    return True, int(ttl)


async def record_failure(redis: "Redis", username: str) -> int:
    """INCR fails counter. When threshold reached, also SET locked flag.

    Returns the new fails count.
    """
    fails = await redis.incr(_fails_key(username))
    if fails == 1:
        # First failure in the window - attach the 10-min TTL
        await redis.expire(_fails_key(username), FAILS_TTL_SECONDS)
    if fails >= FAILS_THRESHOLD:
        await redis.set(_locked_key(username), "1", ex=LOCKOUT_TTL_SECONDS)
    return int(fails)


async def clear_lockout(redis: "Redis", username: str) -> None:
    """Delete both fails counter and lockout flag. Called on successful login."""
    await redis.delete(_fails_key(username), _locked_key(username))


async def admin_unlock(redis: "Redis", username: str) -> None:
    """Admin-initiated unlock - same effect as a successful login's clear.

    Used by POST /api/admin/users/{id}/unlock (plan 09-04).
    """
    await clear_lockout(redis, username)
