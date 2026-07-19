"""Async Redis client - per-event-loop cache.

Thin wrapper over `redis.asyncio.Redis.from_url` using `settings.REDIS_URL`.

A single module-level singleton breaks under Dramatiq workers: each actor
invocation runs `asyncio.run(...)` which creates and then CLOSES a fresh event
loop. A cached client built in loop A holds a Future bound to loop A; when
loop B reuses it the redis library raises `RuntimeError: Event loop is closed`
(connection.disconnect → transport.close → call_soon on closed loop).

Per-loop caching keeps the FastAPI single-loop fast path (one client for the
whole app lifetime) and also makes worker actors safe - each `asyncio.run()`
gets its own client, transparently. Stale entries from finished loops are
evicted on next access.
"""
from __future__ import annotations

import asyncio
import weakref

import redis as redis_sync
from redis.asyncio import Redis

from app.config import settings

# Map loop -> client. WeakKeyDictionary auto-evicts entries when the loop
# is garbage-collected.
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Redis]" = (
    weakref.WeakKeyDictionary()
)


async def get_redis() -> Redis:
    """Return an async Redis client bound to the current event loop.

    Builds one per loop on first call; returns the cached instance thereafter.
    Safe under Dramatiq workers (per-`asyncio.run()` loop) and FastAPI
    (single long-lived loop).
    """
    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None:
        client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        _clients[loop] = client
    return client


async def close_redis() -> None:
    """Close the client bound to the current event loop (FastAPI shutdown hook)."""
    loop = asyncio.get_running_loop()
    client = _clients.pop(loop, None)
    if client is not None:
        await client.aclose()


def get_sync_redis() -> "redis_sync.Redis":
    """Return a synchronous Redis client for sync worker/scheduler contexts.

    Async code paths must use `get_redis()`; this exists for the handful of
    blocking helpers (e.g. robots.txt caching) that run outside an event loop.
    """
    return redis_sync.Redis.from_url(settings.REDIS_URL, decode_responses=True)
