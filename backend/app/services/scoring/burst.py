"""Burst suppression helpers for webhook_dispatcher.py — SCR-05.

Implements a Redis sliding-window cap: at most BURST_HIGH_CAP HIGH-tier (S+A)
webhook fires per project per BURST_WINDOW_SEC rolling window.

References:
  - 15-CONTEXT.md §"Burst suppression"
  - 15-RESEARCH.md §"Pattern 4" + §"Code Examples — Redis Sliding Window (Sync)"
  - 15-RESEARCH.md §"Pitfall 5" — do NOT use async get_redis() here; the webhook
    dispatcher runs in a Dramatiq worker thread with a synchronous redis_lib.Redis
    client. Mixing asyncio.run() into a sync worker causes nested event loop errors.

Roadmap pitfall H-1: burst suppression guard prevents score-driven webhook floods
when 50 CVEs ingest simultaneously all scoring HIGH.
"""
from __future__ import annotations

import time

import redis as redis_lib

# --- Constants ----------------------------------------------------------------

BURST_WINDOW_SEC = 3600  # 1 hour rolling window (seconds)
BURST_HIGH_CAP = 5       # max S+A tier webhook fires per project per window


# --- Internal helpers ---------------------------------------------------------

def _key(project_id: str) -> str:
    """Redis ZSET key for a project's high-tier dispatch sliding window."""
    return f"burst:project:{project_id}:high"


# --- Public API ---------------------------------------------------------------

def is_burst_suppressed(r: redis_lib.Redis, project_id: str) -> bool:
    """Return True iff the project has reached its HIGH-tier webhook cap.

    Uses a Redis ZSET as a sliding window:
      1. Remove stale members (older than BURST_WINDOW_SEC ago).
      2. Count remaining active members.
      3. Return True if count >= BURST_HIGH_CAP (cap reached, suppress this fire).

    The ZREMRANGEBYSCORE + ZCARD pair is pipelined for efficiency. No write
    happens here — only reads. This keeps the function safe to call speculatively
    before deciding whether to record.

    Args:
        r:          Sync redis_lib.Redis client (passed from webhook_dispatcher).
        project_id: String project UUID — used as part of the Redis key.

    Returns:
        True if the project has already fired BURST_HIGH_CAP+ HIGH-tier webhooks
        in the current rolling window; False if capacity remains.
    """
    key = _key(project_id)
    now_ms = int(time.time() * 1000)
    window_start_ms = now_ms - (BURST_WINDOW_SEC * 1000)

    pipe = r.pipeline()
    pipe.zremrangebyscore(key, "-inf", window_start_ms)  # evict stale entries
    pipe.zcard(key)                                        # count active entries
    _, count = pipe.execute()
    return int(count) >= BURST_HIGH_CAP


def record_high_tier_dispatch(r: redis_lib.Redis, project_id: str) -> None:
    """Record a successful HIGH-tier webhook dispatch in the sliding window.

    ZADDs a unique member (epoch-ms + monotonic counter suffix) with score=epoch-ms
    so ZREMRANGEBYSCORE can evict by timestamp while each rapid successive call
    produces a DISTINCT member. Using only epoch-ms as the member would cause
    multiple calls within the same millisecond to overwrite the same entry
    (ZADD updates score in place for an existing member), keeping ZCARD below the
    expected count and allowing more events through than BURST_HIGH_CAP.

    EXPIRE is set to 2× the window to ensure the key survives across the boundary
    without indefinite growth.

    Args:
        r:          Sync redis_lib.Redis client (passed from webhook_dispatcher).
        project_id: String project UUID — used as part of the Redis key.
    """
    import uuid as _uuid

    key = _key(project_id)
    now_ms = int(time.time() * 1000)
    # Unique member: epoch-ms + UUID suffix guarantees distinct ZSET entries even
    # when called multiple times within the same millisecond.
    member = f"{now_ms}:{_uuid.uuid4()}"

    pipe = r.pipeline()
    pipe.zadd(key, {member: now_ms})         # member=unique, score=timestamp_ms
    pipe.expire(key, BURST_WINDOW_SEC * 2)  # safety TTL = 2× window
    pipe.execute()


# --- Generic key-based API (MON-05) --------------------------------
#
# Parallel API to is_burst_suppressed / record_high_tier_dispatch but accepts
# an explicit Redis key instead of deriving it from a project_id.
#
# Usage (monitoring dispatcher):
#   key = f"burst:source:{source_id}:hour"
#   if not is_burst_suppressed_key(r, key, cap=5):
#       record_dispatch_key(r, key)
#       ... dispatch alert ...
#
# The project-scoped functions above are NOT modified — callers are
# unaffected.

def is_burst_suppressed_key(r: redis_lib.Redis, key: str, cap: int) -> bool:
    """Generic sliding-window suppression check using an explicit Redis ZSET key.

    Mirrors is_burst_suppressed but accepts any key string so the same Redis
    ZSET pattern can be reused for monitoring source-hour buckets
    (key shape: ``burst:source:{source_id}:hour``) alongside the project-scoped
    high-tier keys (``burst:project:{id}:high``).

    Uses BURST_WINDOW_SEC = 3600 (same rolling window as the project variant).

    Args:
        r:   Sync redis_lib.Redis client.
        key: Fully-qualified Redis ZSET key (caller constructs the namespace).
        cap: Maximum allowed dispatches within the rolling window.

    Returns:
        True if ``cap`` or more entries exist within the window (suppress this
        dispatch); False if capacity remains.
    """
    now_ms = int(time.time() * 1000)
    window_start_ms = now_ms - (BURST_WINDOW_SEC * 1000)
    pipe = r.pipeline()
    pipe.zremrangebyscore(key, "-inf", window_start_ms)
    pipe.zcard(key)
    _, count = pipe.execute()
    return int(count) >= cap


def record_dispatch_key(r: redis_lib.Redis, key: str) -> None:
    """Record a dispatch event under an explicit Redis ZSET key.

    Mirrors record_high_tier_dispatch but uses the caller-supplied key.
    TTL = 2 × BURST_WINDOW_SEC for safety margin (same as project variant).

    Args:
        r:   Sync redis_lib.Redis client.
        key: Fully-qualified Redis ZSET key (caller constructs the namespace).
    """
    import uuid as _uuid

    now_ms = int(time.time() * 1000)
    # Unique member: epoch-ms + UUID suffix prevents ZADD from overwriting an
    # existing member when two dispatches land in the same millisecond.
    member = f"{now_ms}:{_uuid.uuid4()}"
    pipe = r.pipeline()
    pipe.zadd(key, {member: now_ms})
    pipe.expire(key, BURST_WINDOW_SEC * 2)
    pipe.execute()
