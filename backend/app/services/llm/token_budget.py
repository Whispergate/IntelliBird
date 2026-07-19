"""Atomic Redis token budget counter - AI-06.

Implements a per-project, per-UTC-day token budget with Lua-based atomic
check-and-increment to prevent the GET + INCRBY race condition that would
allow concurrent requests to jointly exceed the daily cap.

Redis key shape:
  ai:budget:project:{project_id}:day:{YYYYMMDD}

where YYYYMMDD is in UTC (rolls at 00:00 UTC).  EX=172800 (2 days) provides
a safety overlap so the previous day's counter is still readable for display
after midnight while the new day accumulates.

Public API:
  check_and_reserve_budget(redis, project_id, estimated_tokens, cap) -> (bool, int)
  record_actual_tokens(redis, project_id, delta) -> int
  budget_key(project_id) -> str          (exposed for tests)
  seconds_until_utc_midnight() -> int    (used for Retry-After header)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BUDGET_TTL_SECONDS: int = 172800  # 2 days - safety overlap across midnight

# ---------------------------------------------------------------------------
# Lua script - atomic check-then-increment
# ---------------------------------------------------------------------------

BUDGET_LUA: str = """
local key = KEYS[1]
local increment = tonumber(ARGV[1])
local cap = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local current = tonumber(redis.call('GET', key) or '0')
if current + increment > cap then
  return {0, current}
end
local new_val = redis.call('INCRBY', key, increment)
redis.call('EXPIRE', key, ttl)
return {1, new_val}
"""

# ---------------------------------------------------------------------------
# Key helper
# ---------------------------------------------------------------------------


def budget_key(project_id) -> str:
    """Return the Redis key for the current UTC day's budget counter."""
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"ai:budget:project:{project_id}:day:{day}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def check_and_reserve_budget(
    redis,
    project_id,
    estimated_tokens: int,
    cap: int,
) -> tuple[bool, int]:
    """Atomically check and reserve tokens against the daily budget.

    Uses a Lua script so the GET + INCRBY is executed atomically in Redis -
    no two concurrent callers can both pass the cap check and both increment.

    Args:
        redis:            Async redis.asyncio.Redis client.
        project_id:       Project UUID (any type - coerced to str in key).
        estimated_tokens: Pre-flight estimate from litellm.token_counter.
        cap:              Daily token cap (from projects.ai_daily_token_cap).

    Returns:
        (allowed, current_used)
          allowed=True  → counter incremented by estimated_tokens
          allowed=False → counter unchanged; current_used is the current value
    """
    key = budget_key(project_id)
    result = await redis.eval(BUDGET_LUA, 1, key, estimated_tokens, cap, BUDGET_TTL_SECONDS)
    allowed, used = result
    return bool(int(allowed)), int(used)


async def record_actual_tokens(
    redis,
    project_id,
    delta: int,
) -> int:
    """Adjust the budget counter after LLM completion.

    Call this after the streaming response completes with:
      delta = actual_total_tokens - estimated_input_tokens

    A positive delta means the call consumed more tokens than estimated
    (output tokens added); a negative delta means the estimate was high
    (rare for input-only estimates).

    Returns the new counter value.  If delta == 0, no Redis call is made.
    """
    if delta == 0:
        return 0
    key = budget_key(project_id)
    new_val = await redis.incrby(key, delta)
    await redis.expire(key, BUDGET_TTL_SECONDS)
    return int(new_val)


def seconds_until_utc_midnight() -> int:
    """Return seconds remaining until 00:00:00 UTC (used for Retry-After header)."""
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((tomorrow - now).total_seconds())
