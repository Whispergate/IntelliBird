"""rescore_project Dramatiq actor — Phase 15 / SCR-02.

Runs on the dedicated ``scoring`` queue (H-3 isolation: score recomputes never
block RSS/NVD/TAXII/EASM/brand ingest workers on the default ``ingest`` or
``brand-monitor`` queues).

Per-loop async engine pattern (mandatory — see RESEARCH.md §"Pitfall 2"):
    Dramatiq worker threads each run in their own asyncio event loop. A module-
    global async_engine would bind its asyncpg connection pool to the FIRST loop
    it touches; reuse on a later loop raises "Future attached to a different loop".
    Solution: create a fresh create_async_engine INSIDE the actor body (_async_rescore)
    and await engine.dispose() in a finally block — guarantees no connection leak.
"""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import dramatiq
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

log = logging.getLogger(__name__)


async def _async_rescore(project_id: UUID) -> dict:
    """Per-loop async engine wrapper — called from asyncio.run() in actor body.

    settings is imported lazily inside the async function body so that importing
    this module (e.g. in unit tests) does not hard-require env vars at import time.
    Engine is disposed in finally so a mid-rescore exception does not leak
    database connections across Dramatiq retry attempts.
    """
    from app.config import settings  # noqa: PLC0415 — lazy import; see module docstring
    from app.services.redis_client import get_redis  # noqa: PLC0415 — lazy import

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

    # SCR-02 advisory gap closure (plan 15-11): in-progress flag for status polling.
    # Key shape: rescore:project:{uuid}:active. TTL=1800s safety net so a crashed
    # actor (kill -9, OOM) does not leave the flag set forever. DEL in finally
    # handles the normal success+failure path.
    flag_key = f"rescore:project:{project_id}:active"
    redis = None
    try:
        try:
            redis = await get_redis()
            await redis.set(flag_key, "1", ex=1800)
        except Exception as exc:  # noqa: BLE001 — Redis unavailability must not fail rescore
            log.warning(
                "rescore_inprogress_flag_set_failed project_id=%s error=%r",
                project_id,
                exc,
            )

        async with session_factory() as session:
            from app.services.scoring.rescore import rescore_project_events  # noqa: PLC0415
            return await rescore_project_events(session, project_id)
    finally:
        if redis is not None:
            try:
                await redis.delete(flag_key)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "rescore_inprogress_flag_clear_failed project_id=%s error=%r",
                    project_id,
                    exc,
                )
        await engine.dispose()


@dramatiq.actor(
    queue_name="scoring",
    max_retries=2,
    min_backoff=5_000,
    max_backoff=60_000,
)
def rescore_project(project_id_str: str) -> None:
    """Dramatiq actor — recompute scores for all events in a project.

    Args:
        project_id_str: UUID string of the project to rescore (Dramatiq
                        serialises actor args as JSON strings).

    On success: logs rescore_project_complete with stats dict.
    On failure: logs rescore_project_failed and re-raises so Dramatiq
    applies the configured retry policy (max_retries=2).
    """
    project_id = UUID(project_id_str)  # raises ValueError on bad UUID — fails fast
    try:
        stats = asyncio.run(_async_rescore(project_id))
        log.info(
            "rescore_project_complete project_id=%s stats=%s",
            project_id_str,
            stats,
        )
    except Exception as exc:
        log.exception(
            "rescore_project_failed project_id=%s error=%r",
            project_id_str,
            exc,
        )
        raise
