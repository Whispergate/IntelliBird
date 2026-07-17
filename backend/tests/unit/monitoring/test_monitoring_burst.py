"""MON-05 burst suppression — plan 16-03.

Tests the burst suppression key shape generalisation for monitoring alerts:
cap=5 alerts/source/hour using Redis ZSET sliding window with key
'burst:source:{source_id}:hour', isolated from project-scoped scoring keys.

Uses a ZSET-capable in-process stub (mirrors dispatcher test pattern
of using a FakeRedis stub rather than requiring a running Redis server).
"""
from __future__ import annotations

import time
from typing import Any

import pytest

from app.services.scoring.burst import (
    BURST_WINDOW_SEC,
    is_burst_suppressed_key,
    record_dispatch_key,
)


# ---------------------------------------------------------------------------
# ZSET-capable Redis stub
# ---------------------------------------------------------------------------

class FakeRedisZSet:
    """Minimal Redis stub implementing sorted-set ops used by burst.py.

    Supports: zadd, zremrangebyscore, zcard, expire, pipeline.
    """

    def __init__(self) -> None:
        self._zsets: dict[str, dict[str, float]] = {}  # key -> {member: score}

    def zadd(self, key: str, mapping: dict[str, float]) -> int:
        bucket = self._zsets.setdefault(key, {})
        added = 0
        for member, score in mapping.items():
            if member not in bucket:
                added += 1
            bucket[member] = score
        return added

    def zremrangebyscore(self, key: str, min_score: Any, max_score: Any) -> int:
        bucket = self._zsets.get(key, {})
        min_val = float("-inf") if min_score == "-inf" else float(min_score)
        max_val = float("inf") if max_score == "+inf" else float(max_score)
        to_remove = [m for m, s in bucket.items() if min_val <= s <= max_val]
        for m in to_remove:
            del bucket[m]
        return len(to_remove)

    def zcard(self, key: str) -> int:
        return len(self._zsets.get(key, {}))

    def expire(self, key: str, ttl: int) -> None:
        pass  # TTL not simulated in-process

    def pipeline(self) -> "_Pipeline":
        return _Pipeline(self)


class _Pipeline:
    """Minimal pipeline stub: buffers calls, executes sequentially on execute()."""

    def __init__(self, r: FakeRedisZSet) -> None:
        self._r = r
        self._calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name: str):
        def _record(*args, **kwargs):
            self._calls.append((name, args, kwargs))
            return self
        return _record

    def execute(self) -> list:
        results = []
        for method, args, kwargs in self._calls:
            results.append(getattr(self._r, method)(*args, **kwargs))
        self._calls.clear()
        return results


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def r() -> FakeRedisZSet:
    """Return a fresh ZSET-capable Redis stub per test."""
    return FakeRedisZSet()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_burst_not_suppressed_initially(r: FakeRedisZSet) -> None:
    """No dispatches recorded — suppression check returns False."""
    key = "burst:source:test-source:hour"
    assert is_burst_suppressed_key(r, key, cap=5) is False


def test_burst_suppressed_after_cap(r: FakeRedisZSet) -> None:
    """6th dispatch for same source within 1 hour is suppressed (cap=5)."""
    key = "burst:source:test-source:hour"
    for _ in range(5):
        record_dispatch_key(r, key)
    # After 5 records, cap=5 is reached — next check is suppressed
    assert is_burst_suppressed_key(r, key, cap=5) is True


def test_burst_not_suppressed_below_cap(r: FakeRedisZSet) -> None:
    """4 dispatches under cap=5 — still not suppressed."""
    key = "burst:source:test-source:hour"
    for _ in range(4):
        record_dispatch_key(r, key)
    assert is_burst_suppressed_key(r, key, cap=5) is False


def test_burst_window_3600s() -> None:
    """Sliding window constant is exactly 3600 seconds."""
    assert BURST_WINDOW_SEC == 3600


def test_record_dispatch_key_isolated_from_project_keys(r: FakeRedisZSet) -> None:
    """'burst:source:{id}:hour' key does not collide with 'burst:project:{id}:high'."""
    source_key = "burst:source:abc:hour"
    project_key = "burst:project:abc:high"

    # Record 5 dispatches on the source key (cap reached)
    for _ in range(5):
        record_dispatch_key(r, source_key)

    # Source key is suppressed
    assert is_burst_suppressed_key(r, source_key, cap=5) is True
    # Project key is completely unaffected
    assert is_burst_suppressed_key(r, project_key, cap=5) is False
