"""Enrichment provider circuit breaker — Phase 23 / ENRICH-03.

Tracks consecutive 429 (quota-exceeded) responses from external providers.
After CB_THRESHOLD failures within CB_WINDOW_TTL seconds, the breaker
opens (enrich:cb key set) and all requests for that provider are blocked
until the key expires after CB_OPEN_TTL seconds.

Redis key shapes:
  enrich:cb:{provider}:{project_scope}              TTL=3600s (breaker open)
  enrich:cb:fails:{provider}:{project_scope}        TTL=300s  (failure counter)

State machine:
  CLOSED → record_quota_failure x3 → OPEN (enrich:cb set, fail key deleted)
  OPEN   → auto-reset after CB_OPEN_TTL (key expiry)
  OPEN   → is_breaker_open → True
  CLOSED → is_breaker_open → False

NOTE: Shodan 401 (insufficient plan) must NOT call record_quota_failure.
Handle 401 in shodan.py by returning None without touching Redis.

Public API:
  is_breaker_open(redis, provider, project_scope) -> bool
  record_quota_failure(redis, provider, project_scope)
  record_success(redis, provider, project_scope)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

CB_OPEN_TTL: int = 3600    # 1 hour — breaker stays open this long
CB_WINDOW_TTL: int = 300   # 5 minutes — failure counter window
CB_THRESHOLD: int = 3      # consecutive failures before opening


def _open_key(provider: str, project_scope: str) -> str:
    return f"enrich:cb:{provider}:{project_scope}"


def _fail_key(provider: str, project_scope: str) -> str:
    return f"enrich:cb:fails:{provider}:{project_scope}"


async def is_breaker_open(redis, provider: str, project_scope: str) -> bool:
    """Return True if the circuit breaker is open for this provider+scope."""
    return await redis.exists(_open_key(provider, project_scope)) == 1


async def record_quota_failure(redis, provider: str, project_scope: str) -> None:
    """Record a consecutive quota failure (HTTP 429 or quota exceeded).

    On the 3rd consecutive failure within CB_WINDOW_TTL seconds:
      - Sets the breaker-open key (TTL=CB_OPEN_TTL)
      - Deletes the failure counter (window resets)
      - Logs a warning

    Call count resets when the failure counter key expires (CB_WINDOW_TTL)
    or when record_success() is called.
    """
    fkey = _fail_key(provider, project_scope)
    count = await redis.incr(fkey)
    await redis.expire(fkey, CB_WINDOW_TTL)

    if count >= CB_THRESHOLD:
        okey = _open_key(provider, project_scope)
        await redis.set(okey, "1", ex=CB_OPEN_TTL)
        await redis.delete(fkey)
        logger.warning(
            "enrich_circuit_breaker_opened provider=%s scope=%s threshold=%d",
            provider,
            project_scope,
            CB_THRESHOLD,
        )


async def record_success(redis, provider: str, project_scope: str) -> None:
    """Reset the failure counter after a successful provider response.

    Does NOT close an already-open breaker — the breaker self-heals after
    CB_OPEN_TTL expires. This only prevents the failure window from
    accumulating across successful calls.
    """
    fkey = _fail_key(provider, project_scope)
    await redis.delete(fkey)


__all__ = ["is_breaker_open", "record_quota_failure", "record_success"]
