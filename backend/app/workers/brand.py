"""Brand Protection Dramatiq actor.

Wraps `app.services.brand_monitor.scan_project` on queue='brand-monitor' (M-8 CPU
isolation lock - keeps scan cycles off the default queue so NVD/RSS/TAXII/EASM
throughput is unaffected by dnstwist subprocess CPU).

Per-loop async engine pattern (easm.py lesson):
    Dramatiq worker threads run each actor invocation in its own asyncio event
    loop. A module-global `async_engine` binds its asyncpg connection pool to
    the FIRST event loop it touches; reuse on a later loop raises
    "Future attached to a different loop". Fix: create a fresh
    `create_async_engine` INSIDE the actor body and `await engine.dispose()` in
    a finally block. This also guarantees no connection leak on actor failure.
"""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import dramatiq
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.services.brand_monitor import scan_project

log = logging.getLogger(__name__)


async def _async_scan(project_id: UUID) -> dict[str, int]:
    """Create a per-loop async engine, open one session, run scan_project, dispose.

    Engine is disposed in finally so a mid-scan exception does not leak connections.
    """
    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        future=True,
        pool_size=2,
        max_overflow=2,
    )
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession,
    )
    try:
        async with session_factory() as session:
            return await scan_project(session, project_id)
    finally:
        await engine.dispose()


@dramatiq.actor(
    queue_name="brand-monitor",
    max_retries=2,
    min_backoff=5_000,
    max_backoff=60_000,
)
def brand_monitor_scan_project(project_id_str: str) -> None:
    """Actor entry point - sync wrapper around async scan_project.

    `project_id_str` is a string UUID (Dramatiq serialises args as JSON).
    On success: logs `brand_monitor_scan_complete` with stats dict.
    On failure: logs `brand_monitor_scan_failed` and re-raises so Dramatiq
    applies the configured retry policy.
    """
    project_id = UUID(project_id_str)
    try:
        stats = asyncio.run(_async_scan(project_id))
        log.info(
            "brand_monitor_scan_complete project_id=%s stats=%s",
            project_id_str,
            stats,
        )
    except Exception as exc:
        log.exception(
            "brand_monitor_scan_failed project_id=%s error=%r",
            project_id_str,
            exc,
        )
        raise
