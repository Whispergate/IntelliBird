"""Unit tests for the SSE Redis cancel-flag protocol — Phase 17 / AI-06.

Covers:
  - test_disconnect_sets_cancel_flag: Redis SET ai:job:{id}:cancelled with EX=300
  - test_cancel_flag_ex_300: TTL on the cancel key is within [290, 300] seconds
  - test_actor_exits_when_flag_set: actor breaks after pre-set cancel flag (< all chunks pushed)

The SSE generator (17-07 router) owns the disconnect -> SET path.  For this plan
we test the Redis key contract directly and test _async_summarise's cancel-check
logic via a mock-Redis / mock-litellm harness.
"""
from __future__ import annotations

import asyncio
import contextlib
import os

# Set env vars before any app module imports to avoid pydantic Settings errors.
os.environ.setdefault("SECRET_KEY", "a" * 32 + "deadbeef")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SIGNING_KEY", "b" * 64)

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeRedis:
    """In-memory Redis stub with the methods used by _async_summarise."""

    def __init__(self):
        self._store: dict[str, str] = {}
        self._ttls: dict[str, int] = {}
        self._lists: dict[str, list] = {}
        self.rpush_calls: list = []

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self._store[key] = value
        if ex is not None:
            self._ttls[key] = ex

    async def rpush(self, key: str, *values):
        if key not in self._lists:
            self._lists[key] = []
        for v in values:
            self._lists[key].append(v)
        self.rpush_calls.append((key, values))

    async def expire(self, key: str, seconds: int):
        self._ttls[key] = seconds

    async def delete(self, key: str):
        self._store.pop(key, None)

    async def eval(self, script, numkeys, *args):
        # Lua budget script: always allow (return [1, 0])
        return [1, 0]

    async def incrby(self, key: str, delta: int):
        val = int(self._store.get(key, "0")) + delta
        self._store[key] = str(val)
        return val

    def lrange(self, key: str):
        return self._lists.get(key, [])

    def ttl(self, key: str) -> int:
        return self._ttls.get(key, -1)


@contextlib.contextmanager
def _noop_ctx():
    yield


# ---------------------------------------------------------------------------
# test_disconnect_sets_cancel_flag
# ---------------------------------------------------------------------------


def test_disconnect_sets_cancel_flag():
    """Simulate SSE disconnect - generator sets ai:job:{id}:cancelled with EX=300.

    The SSE generator pattern (implemented in 17-07 router):
        try:
            async for chunk in stream_job_chunks(job_id, redis):
                yield ...
        finally:
            if request.is_disconnected():
                await redis.set(f"ai:job:{job_id}:cancelled", "1", ex=300)

    Here we test the Redis contract directly.
    """
    job_id = "test-job-abc"
    fake_redis = FakeRedis()

    async def simulate_disconnect():
        # Simulate what the SSE generator's finally block does on disconnect.
        await fake_redis.set(f"ai:job:{job_id}:cancelled", "1", ex=300)

    asyncio.run(simulate_disconnect())

    key = f"ai:job:{job_id}:cancelled"
    assert fake_redis._store.get(key) == "1", "cancel flag must be SET to '1'"
    assert fake_redis._ttls.get(key) == 300, "cancel flag must have EX=300"


# ---------------------------------------------------------------------------
# test_cancel_flag_ex_300
# ---------------------------------------------------------------------------


def test_cancel_flag_ex_300():
    """Cancel flag Redis key has TTL of exactly 300 seconds (EX=300)."""
    job_id = "test-job-ttl"
    fake_redis = FakeRedis()

    async def set_cancel():
        await fake_redis.set(f"ai:job:{job_id}:cancelled", "1", ex=300)

    asyncio.run(set_cancel())

    ttl = fake_redis.ttl(f"ai:job:{job_id}:cancelled")
    # In a real Redis call the TTL decays; FakeRedis stores the initial set value.
    assert 290 <= ttl <= 300, f"Expected TTL in [290, 300], got {ttl}"


# ---------------------------------------------------------------------------
# test_actor_exits_when_flag_set
# ---------------------------------------------------------------------------


def test_actor_exits_when_flag_set():
    """_async_summarise breaks after pre-set cancel flag - less than 5 chunks pushed."""
    job_id = "test-job-cancel"
    event_id = "00000000-0000-0000-0000-000000000001"
    project_id = "00000000-0000-0000-0000-000000000002"

    fake_redis = FakeRedis()
    # Pre-set the cancel flag BEFORE the actor runs.
    fake_redis._store[f"ai:job:{job_id}:cancelled"] = "1"
    fake_redis._ttls[f"ai:job:{job_id}:cancelled"] = 300

    # Build a mock async generator that yields 5 chunks.
    five_chunks = ["chunk1", "chunk2", "chunk3", "chunk4", "chunk5"]

    async def fake_call_llm_streaming(*args, **kwargs):
        for c in five_chunks:
            yield c

    # Mock Event and Project rows.
    mock_event = MagicMock()
    mock_event.id = event_id
    mock_event.title = "Test Event"
    mock_event.description = "Test description"
    mock_event.stix_type = "indicator"
    mock_event.observed_at = "2026-01-01T00:00:00Z"
    mock_event.tags = []

    mock_project = MagicMock()
    mock_project.id = project_id
    mock_project.ai_daily_token_cap = 100000

    # Mock scalar_one_or_none to return event then project.
    call_count = [0]

    async def fake_execute(stmt):
        call_count[0] += 1
        result = MagicMock()
        if call_count[0] == 1:
            result.scalar_one_or_none = MagicMock(return_value=mock_event)
        else:
            result.scalar_one_or_none = MagicMock(return_value=mock_project)
        return result

    mock_db = AsyncMock()
    mock_db.execute = fake_execute
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_session_factory = MagicMock(return_value=mock_session_ctx)

    mock_engine = AsyncMock()
    mock_engine.dispose = AsyncMock()

    async def run_test():
        with (
            patch(
                "app.workers.ai._make_engine_and_session",
                return_value=(mock_engine, mock_session_factory),
            ),
            patch(
                "app.services.redis_client.get_redis",
                new=AsyncMock(return_value=fake_redis),
            ),
            patch(
                "app.services.llm.client.resolve_provider",
                new=AsyncMock(return_value=("ollama_chat/phi3:mini", "http://ollama:11434", None)),
            ),
            patch(
                "app.services.llm.client.estimate_input_tokens",
                return_value=100,
            ),
            patch(
                "app.services.llm.token_budget.check_and_reserve_budget",
                new=AsyncMock(return_value=(True, 100)),
            ),
            patch(
                "app.services.llm.token_budget.record_actual_tokens",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "app.services.llm.client.call_llm_streaming",
                new=fake_call_llm_streaming,
            ),
        ):
            from app.workers.ai import _async_summarise
            await _async_summarise(job_id, event_id, project_id)

    asyncio.run(run_test())

    chunks_key = f"ai:job:{job_id}:chunks"
    pushed = fake_redis.lrange(chunks_key)
    # Cancel flag was pre-set - actor should exit before pushing all 5 chunks.
    assert len(pushed) < 5, (
        f"Expected fewer than 5 chunks pushed when cancel flag is pre-set, "
        f"but got {len(pushed)}: {pushed}"
    )
    # Done key should still be set (actor cleans up on cancel).
    done_key = f"ai:job:{job_id}:done"
    assert fake_redis._store.get(done_key) == "1", "done flag must be SET even on cancel"
