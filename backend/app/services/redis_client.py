"""Async Redis client singleton.

Thin wrapper over `redis.asyncio.Redis.from_url` using `settings.REDIS_URL`.
Callers that already have a Redis handle (e.g. brand_preview, lockout) should
prefer dependency injection; this helper exists for routers/actors that need a
lazily-initialised shared client.
"""
from __future__ import annotations

from redis.asyncio import Redis

from app.config import settings

_redis: Redis | None = None


async def get_redis() -> Redis:
    """Return the process-wide async Redis client, creating it on first use."""
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


async def close_redis() -> None:
    """Close the shared client (called from FastAPI shutdown hook)."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
