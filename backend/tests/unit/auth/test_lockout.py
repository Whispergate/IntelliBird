"""Login lockout counter unit tests — AUTH-04."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _get_redis():
    try:
        import redis.asyncio as aioredis
    except ImportError:
        pytest.skip("redis package not installed")
    import os
    return aioredis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


async def test_record_failure_increments(redis_flush):
    redis = await _get_redis()
    try:
        from app.security.lockout import record_failure
        n1 = await record_failure(redis, "alice")
        n2 = await record_failure(redis, "alice")
        assert n1 == 1
        assert n2 == 2
    finally:
        await redis.aclose()


async def test_lockout_at_five_failures(redis_flush):
    redis = await _get_redis()
    try:
        from app.security.lockout import record_failure, is_locked
        for _ in range(5):
            await record_failure(redis, "bob")
        locked, retry = await is_locked(redis, "bob")
        assert locked is True
        assert 0 < retry <= 1800
    finally:
        await redis.aclose()


async def test_is_locked_false_below_threshold(redis_flush):
    redis = await _get_redis()
    try:
        from app.security.lockout import record_failure, is_locked
        for _ in range(4):
            await record_failure(redis, "carol")
        locked, retry = await is_locked(redis, "carol")
        assert locked is False
        assert retry == 0
    finally:
        await redis.aclose()


async def test_clear_lockout(redis_flush):
    redis = await _get_redis()
    try:
        from app.security.lockout import record_failure, clear_lockout, is_locked
        for _ in range(5):
            await record_failure(redis, "dave")
        await clear_lockout(redis, "dave")
        locked, _ = await is_locked(redis, "dave")
        assert locked is False
    finally:
        await redis.aclose()


async def test_admin_unlock_alias(redis_flush):
    redis = await _get_redis()
    try:
        from app.security.lockout import record_failure, admin_unlock, is_locked
        for _ in range(5):
            await record_failure(redis, "eve")
        await admin_unlock(redis, "eve")
        locked, _ = await is_locked(redis, "eve")
        assert locked is False
    finally:
        await redis.aclose()


async def test_dummy_username_increments_counter(redis_flush):
    """PITFALL 7 — record_failure runs even for non-existent users to prevent enumeration."""
    redis = await _get_redis()
    try:
        from app.security.lockout import record_failure, is_locked
        for _ in range(5):
            await record_failure(redis, "nobody-exists-attacker-probe")
        locked, _ = await is_locked(redis, "nobody-exists-attacker-probe")
        assert locked is True
    finally:
        await redis.aclose()
