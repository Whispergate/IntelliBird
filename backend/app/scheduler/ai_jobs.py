"""APScheduler AI jobs - AI-06, AI-07, SCR-04.

Registers three CronTrigger jobs:
  ai_digest_all      - 06:00 UTC daily, dispatches ai_digest_project for opted-in projects
  ai_suggestion_expiry - 01:00 UTC daily, marks pending suggestions > 30 days as discarded
  ai_nightly_rerank  - 02:00 UTC daily, dispatches ai_rescore_project for opted-in projects

Pattern mirrors monitoring_jobs.py exactly - see scheduler/jobs.py bootstrap.

Nightly rerank: only projects WHERE ai_rerank_enabled=True (Pitfall 8 - must not rerank
all projects, only those that have opted in). Same guard for digest.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, update

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Job functions
# ---------------------------------------------------------------------------


def ai_digest_all_job() -> None:
    """Dispatch ai_digest_project for every project where ai_digest_enabled=True."""
    import asyncio  # noqa: PLC0415

    from app.workers.ai import ai_digest_project  # noqa: PLC0415

    async def _go():
        from app.database import async_session_factory  # noqa: PLC0415
        from app.models.projects import Project  # noqa: PLC0415

        async with async_session_factory() as db:
            rows = (
                await db.execute(
                    select(Project.id).where(Project.ai_digest_enabled.is_(True))
                )
            ).scalars().all()
            for pid in rows:
                try:
                    ai_digest_project.send(str(pid))
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "ai_digest_all_job_enqueue_failed project_id=%s error=%s", pid, exc
                    )
        logger.info("ai_digest_all_job_dispatched count=%d", len(rows))

    asyncio.run(_go())


def ai_nightly_rerank_job() -> None:
    """Dispatch ai_rescore_project for every project where ai_rerank_enabled=True."""
    import asyncio  # noqa: PLC0415

    from app.workers.ai import ai_rescore_project  # noqa: PLC0415

    async def _go():
        from app.database import async_session_factory  # noqa: PLC0415
        from app.models.projects import Project  # noqa: PLC0415

        async with async_session_factory() as db:
            rows = (
                await db.execute(
                    select(Project.id).where(Project.ai_rerank_enabled.is_(True))
                )
            ).scalars().all()
            for pid in rows:
                try:
                    ai_rescore_project.send(str(pid))
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "ai_nightly_rerank_job_enqueue_failed project_id=%s error=%s", pid, exc
                    )
        logger.info("ai_nightly_rerank_job_dispatched count=%d", len(rows))

    asyncio.run(_go())


def ai_suggestion_expiry_job() -> None:
    """Mark pending suggestions older than 30 days as discarded.

    Suggestion expiry: pending -> discarded after 30 days.
    Confirmed/discarded rows never auto-expire (only pending transitions).
    """
    import asyncio  # noqa: PLC0415

    async def _go():
        from app.database import async_session_factory  # noqa: PLC0415
        from app.models.ai import AISuggestion  # noqa: PLC0415

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        async with async_session_factory() as db:
            result = await db.execute(
                update(AISuggestion)
                .where(
                    AISuggestion.status == "pending",
                    AISuggestion.created_at < cutoff,
                )
                .values(
                    status="discarded",
                    decided_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
            affected = result.rowcount if hasattr(result, "rowcount") else 0
        logger.info("ai_suggestion_expiry_job_complete discarded=%d", affected)

    asyncio.run(_go())


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_ai_jobs(scheduler) -> None:
    """Register all AI CronTrigger jobs onto the given APScheduler instance.

    Job IDs (stable - used by tests + ops):
      - ai_digest_all         : CronTrigger(hour=6, minute=0, UTC)
      - ai_suggestion_expiry  : CronTrigger(hour=1, minute=0, UTC)
      - ai_nightly_rerank     : CronTrigger(hour=2, minute=0, UTC)
    """
    scheduler.add_job(
        ai_digest_all_job,
        CronTrigger(hour=6, minute=0, timezone="UTC"),
        id="ai_digest_all",
        replace_existing=True,
    )
    scheduler.add_job(
        ai_suggestion_expiry_job,
        CronTrigger(hour=1, minute=0, timezone="UTC"),
        id="ai_suggestion_expiry",
        replace_existing=True,
    )
    scheduler.add_job(
        ai_nightly_rerank_job,
        CronTrigger(hour=2, minute=0, timezone="UTC"),
        id="ai_nightly_rerank",
        replace_existing=True,
    )
    logger.info("scheduler_registered ai_digest_all + ai_suggestion_expiry + ai_nightly_rerank")
