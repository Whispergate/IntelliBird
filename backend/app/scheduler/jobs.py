"""APScheduler process — dispatches Dramatiq actors on cron triggers.

Phase 1 established attack_weekly_refresh + attack_first_boot.
Phase 2 adds per-source poll_{rss,taxii,nvd} IntervalTrigger jobs
loaded from the sources table at startup (D-32).
Phase 3 Plan 06 adds a daemon thread subscribing to Redis pub/sub for
live source CRUD reload without scheduler restart.
"""
from __future__ import annotations

import json
import logging
import signal
import sys
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SyncSession

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

# Importing broker registers the actors on the Redis broker
from app.workers import broker as _broker  # noqa: F401
from app.workers.bootstrap import bootstrap_attack
from app.workers.nvd import poll_nvd
from app.workers.rss import poll_rss
from app.workers.taxii import poll_taxii
from app.services.archiver import archive_once
from app.services.source_events import RELOAD_CHANNEL

logger = logging.getLogger(__name__)

# feed_type -> actor lookup. Must match sources.feed_type enum (migration 001).
# 'custom' is intentionally absent — Phase 3 will handle operator-defined types.
_ACTOR_MAP: dict[str, object] = {
    "rss": poll_rss,
    "taxii": poll_taxii,
    "nvd": poll_nvd,
}


def refresh_attack() -> None:
    """Wrapper enqueues the Dramatiq actor; APScheduler only fires the enqueue."""
    bootstrap_attack.send()


def archiver_job_wrapper() -> None:
    """Nightly archiver entrypoint — opens a sync session and runs one pass."""
    from app.config import settings  # noqa: PLC0415

    sync_url = settings.DATABASE_URL
    sync_url = sync_url.replace("postgresql+asyncpg://", "postgresql://")
    sync_url = sync_url.replace("+asyncpg", "")
    engine = create_engine(sync_url, future=True)
    try:
        with SyncSession(engine) as session:
            totals = archive_once(session)
            logger.info("archiver_job_completed totals=%s", totals)
    finally:
        engine.dispose()


def _make_dispatch(actor: object, source_id: str):  # type: ignore[no-untyped-def]
    """Closure that sends the actor with the source_id argument."""
    def _dispatch() -> None:
        actor.send(source_id)  # type: ignore[attr-defined]
    return _dispatch


def _load_source_jobs(scheduler: BlockingScheduler) -> None:
    """Read sources table and register one IntervalTrigger job per enabled source.

    Uses a short-lived sync psycopg2 connection — APScheduler is sync.
    Idempotent via replace_existing=True (Pitfall 7). Unknown feed_type
    values are skipped with a structured-log WARNING (defence against
    Phase 3 CRUD introducing new types before the scheduler is updated).
    """
    import psycopg2  # noqa: PLC0415

    from app.config import settings  # noqa: PLC0415

    url = settings.DATABASE_URL
    # psycopg2 accepts plain postgresql:// — strip any asyncpg marker first
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("+asyncpg", "")

    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, feed_type, poll_interval_sec FROM sources "
                "WHERE enabled = true"
            )
            for source_id, feed_type, interval_sec in cur.fetchall():
                actor = _ACTOR_MAP.get(feed_type)
                if actor is None:
                    logger.warning(
                        "scheduler_unknown_feed_type source_id=%s feed_type=%s",
                        source_id,
                        feed_type,
                    )
                    continue
                job_id = f"poll_{feed_type}_{source_id}"
                scheduler.add_job(
                    _make_dispatch(actor, str(source_id)),
                    IntervalTrigger(seconds=int(interval_sec)),
                    id=job_id,
                    replace_existing=True,  # Pitfall 7 — prevents duplicate jobs on restart
                )
                logger.info(
                    "scheduler_registered feed_type=%s source_id=%s interval=%d",
                    feed_type,
                    source_id,
                    interval_sec,
                )
    finally:
        conn.close()


def _reload_handler(scheduler: BlockingScheduler, payload: dict[str, Any]) -> None:
    """Process one reload message: remove deleted jobs, reload the rest.

    Pitfall 8: DELETE publishes {"deleted": [{"feed_type": "...", "source_id": "..."}]}.
    We must remove those specific APScheduler jobs BEFORE _load_source_jobs runs
    (which only adds/updates — it does not remove orphans).
    """
    deleted = payload.get("deleted") or []
    for entry in deleted:
        feed_type = entry.get("feed_type")
        source_id = entry.get("source_id")
        if not feed_type or not source_id:
            continue
        job_id = f"poll_{feed_type}_{source_id}"
        try:
            scheduler.remove_job(job_id)
            logger.info("scheduler_removed_job job_id=%s", job_id)
        except JobLookupError:
            logger.debug("scheduler_remove_job_absent job_id=%s", job_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("scheduler_remove_job_error job_id=%s error=%s", job_id, e)

    try:
        _load_source_jobs(scheduler)
    except Exception as e:  # noqa: BLE001
        logger.warning("scheduler_reload_failed error=%s", e)


def _reload_listener_loop(scheduler: BlockingScheduler) -> None:
    """Daemon thread entrypoint — subscribes to Redis and dispatches reload_handler."""
    import redis as redis_lib  # noqa: PLC0415

    from app.config import settings  # noqa: PLC0415

    try:
        r = redis_lib.from_url(settings.REDIS_URL)
        pubsub = r.pubsub()
        pubsub.subscribe(RELOAD_CHANNEL)
        logger.info("scheduler_reload_listener_subscribed channel=%s", RELOAD_CHANNEL)
        for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                payload = json.loads(message["data"])
            except Exception as e:  # noqa: BLE001
                logger.warning("scheduler_reload_malformed_payload error=%s", e)
                continue
            action = payload.get("action")
            if action != "reload":
                logger.debug("scheduler_reload_unknown_action action=%s", action)
                continue
            _reload_handler(scheduler, payload)
    except Exception as e:  # noqa: BLE001
        logger.warning("scheduler_reload_listener_exited error=%s", e)


def _start_reload_listener(scheduler: BlockingScheduler) -> threading.Thread:
    """Spawn the daemon thread. Returns the thread for testing."""
    t = threading.Thread(
        target=_reload_listener_loop,
        args=(scheduler,),
        name="sources-reload-listener",
        daemon=True,
    )
    t.start()
    return t


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="UTC")
    # Phase 1 jobs (preserved)
    scheduler.add_job(
        refresh_attack,
        CronTrigger(day_of_week="mon", hour=3, minute=0),
        id="attack_weekly_refresh",
        replace_existing=True,
    )
    scheduler.add_job(
        refresh_attack,
        DateTrigger(run_date=datetime.utcnow() + timedelta(seconds=30)),
        id="attack_first_boot",
        replace_existing=True,
    )
    # Phase 3 archiver job — nightly at 03:00 UTC
    scheduler.add_job(
        archiver_job_wrapper,
        CronTrigger(hour=3, minute=0),
        id="archiver_nightly",
        replace_existing=True,
    )
    # Phase 2 per-source ingest jobs
    try:
        _load_source_jobs(scheduler)
    except Exception as e:  # noqa: BLE001
        logger.warning("scheduler_source_load_failed error=%s", e)
    # Phase 6 MAP-05 — geo backfill one-shot at startup (+30s)
    try:
        from app.services.geo_backfill import backfill_geo_once  # noqa: PLC0415
        scheduler.add_job(
            _make_dispatch(backfill_geo_once, "nil"),
            trigger=DateTrigger(
                run_date=datetime.now(timezone.utc) + timedelta(seconds=30)
            ),
            id="geo_backfill_first_boot",
            replace_existing=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("scheduler_geo_backfill_register_failed error=%s", e)
    # Phase 7 — webhook dispatcher tick (60s interval)
    try:
        from app.workers.webhook_dispatcher_actor import webhook_dispatch_tick  # noqa: PLC0415
        scheduler.add_job(
            lambda: webhook_dispatch_tick.send("tick"),
            IntervalTrigger(seconds=60),
            id="webhook_dispatch_tick",
            replace_existing=True,
        )
        logger.info("scheduler_registered webhook_dispatch_tick interval=60")
    except Exception as e:  # noqa: BLE001
        logger.warning("scheduler_webhook_dispatch_register_failed error=%s", e)
    # Phase 3 Plan 06 — live reload listener (daemon thread)
    try:
        _start_reload_listener(scheduler)
    except Exception as e:  # noqa: BLE001
        logger.warning("scheduler_reload_listener_start_failed error=%s", e)
    return scheduler


def main() -> None:
    # SYS-04: JSON line output via structlog bridge (shared with api + workers)
    from app.logging import configure_logging
    configure_logging()
    scheduler = build_scheduler()

    def _shutdown(signum, frame):  # type: ignore[no-untyped-def]
        logger.info("scheduler_shutdown signal=%d", signum)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("scheduler_starting")
    scheduler.start()


if __name__ == "__main__":
    main()
