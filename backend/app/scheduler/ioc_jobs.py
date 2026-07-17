"""APScheduler IOC jobs — IOC-05.

Registers one CronTrigger job:
  ioc_expiry — 03:00 UTC daily, flips status='active' → 'expired'
               for rows where last_seen + (ttl_days * INTERVAL '1 day') < NOW().

Mirrors `scheduler/ai_jobs.py:ai_suggestion_expiry_job` shape.

Soft-expire only — rows are retained (analyst can re-surface via
`?include_expired=true`); re-sighting via the ingest hook flips
expired → active again. This matches CONTEXT.md §"TTL decay".
"""
from __future__ import annotations

import asyncio
import logging

from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


def ioc_expiry_job() -> None:
    """Daily TTL sweep — soft-expire active IOCs whose TTL has elapsed."""

    async def _go() -> None:
        from app.database import async_session_factory  # noqa: PLC0415
        from app.services.iocs import expire_iocs  # noqa: PLC0415

        async with async_session_factory() as session:
            count = await expire_iocs(session)
            logger.info("ioc_expiry_job_complete expired=%d", count)

    asyncio.run(_go())


def register_ioc_jobs(scheduler) -> None:  # type: ignore[no-untyped-def]
    """Register the daily TTL expiry CronTrigger.

    Job IDs (stable — used by tests + ops):
      - ioc_expiry : CronTrigger(hour=3, minute=0, UTC)
    """
    scheduler.add_job(
        ioc_expiry_job,
        CronTrigger(hour=3, minute=0, timezone="UTC"),
        id="ioc_expiry",
        replace_existing=True,
    )
    logger.info("scheduler_registered ioc_expiry")
