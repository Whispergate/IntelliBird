"""Atomic Redis quota gate for enrichment providers - ENRICH-03.

Implements per-minute and per-day quota enforcement using Lua scripts
executed atomically in Redis. The dual-gate approach ensures that
concurrent requests cannot jointly exceed either cap.

Redis key shapes:
  enrich:quota:{provider}:{project_scope}:{minute_bucket}   TTL 70s
  enrich:daily:{provider}:{project_scope}:{YYYYMMDD}        TTL 86400+3600s

Public API:
  check_and_consume_quota(redis, provider, project_scope, minute_cap, daily_cap) -> bool
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider default rate limits (from RESEARCH.md)
# ---------------------------------------------------------------------------

PROVIDER_MINUTE_CAPS: dict[str, int] = {
    "vt": 4,
    "abuseipdb": 60,
    "greynoise": 10,
    "otx": 60,
    "shodan": 1,
    "urlhaus": 60,
    # Passive DNS providers (ENRICH-06)
    "securitytrails": 2,
    "mnemonic": 10,
    "riskiq_community": 12,
}

PROVIDER_DEFAULT_DAILY_CAPS: dict[str, int | None] = {
    "vt": 500,
    "abuseipdb": 1000,
    "greynoise": 50,
    "otx": None,
    "shodan": None,
    "urlhaus": None,
    # Passive DNS providers (ENRICH-06)
    "securitytrails": 50,
    "mnemonic": 1000,
    "riskiq_community": 1000,
}

# ---------------------------------------------------------------------------
# Lua script - atomic check-then-increment (single unit increment)
# Adapted from app/services/llm/token_budget.py BUDGET_LUA.
# Returns {1, new_val} on allow; {0, current} on deny.
# ---------------------------------------------------------------------------

QUOTA_LUA: str = """
local key = KEYS[1]
local cap = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local current = tonumber(redis.call('GET', key) or '0')
if current + 1 > cap then
  return {0, current}
end
local new_val = redis.call('INCRBY', key, 1)
redis.call('EXPIRE', key, ttl)
return {1, new_val}
"""

# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------


def _minute_key(provider: str, project_scope: str) -> str:
    """Return the Redis key for the current UTC minute's quota counter."""
    bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    return f"enrich:quota:{provider}:{project_scope}:{bucket}"


def _daily_key(provider: str, project_scope: str) -> str:
    """Return the Redis key for the current UTC day's quota counter."""
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"enrich:daily:{provider}:{project_scope}:{day}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def check_and_consume_quota(
    redis,
    provider: str,
    project_scope: str,
    minute_cap: int,
    daily_cap: int | None,
) -> bool:
    """Atomically check and consume quota for one provider request.

    Checks per-minute cap first, then per-day cap. If the minute cap is
    exceeded, returns False immediately without touching the daily counter.
    If the daily cap is exceeded after the minute counter was incremented,
    the minute counter is decremented before returning False.

    Args:
        redis:         Async redis.asyncio.Redis client.
        provider:      Provider name (e.g. "vt", "abuseipdb").
        project_scope: "global" or project UUID string.
        minute_cap:    Maximum requests per minute.
        daily_cap:     Maximum requests per day, or None (unlimited).

    Returns:
        True if both quotas have capacity and counters were incremented.
        False if either cap is exceeded - no counter changes persist.
    """
    # Per-minute gate
    minute_key = _minute_key(provider, project_scope)
    result = await redis.eval(QUOTA_LUA, 1, minute_key, minute_cap, 70)
    allowed, _ = result
    if not int(allowed):
        logger.debug(
            "enrich_quota_minute_blocked provider=%s scope=%s", provider, project_scope
        )
        return False

    # Per-day gate (only if a daily cap is configured)
    if daily_cap is not None:
        daily_key = _daily_key(provider, project_scope)
        d_result = await redis.eval(QUOTA_LUA, 1, daily_key, daily_cap, 90000)
        d_allowed, _ = d_result
        if not int(d_allowed):
            # Roll back the minute increment we just consumed
            await redis.decrby(minute_key, 1)
            logger.debug(
                "enrich_quota_daily_blocked provider=%s scope=%s", provider, project_scope
            )
            return False

    return True


__all__ = [
    "check_and_consume_quota",
    "PROVIDER_MINUTE_CAPS",
    "PROVIDER_DEFAULT_DAILY_CAPS",
    "QUOTA_LUA",
]
