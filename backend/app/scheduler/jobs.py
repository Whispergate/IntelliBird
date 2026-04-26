"""APScheduler process — dispatches Dramatiq actors on cron triggers.

 established attack_weekly_refresh + attack_first_boot.
 adds per-source poll_{rss,taxii,nvd} IntervalTrigger jobs
loaded from the sources table at startup.
 Plan 06 adds a daemon thread subscribing to Redis pub/sub for
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
from app.workers.html_scrape import poll_html_scrape
from app.workers.nvd import poll_nvd
from app.workers.rss import poll_rss
from app.workers.taxii import poll_taxii
from app.services.archiver import archive_once
from app.services.source_events import RELOAD_CHANNEL

logger = logging.getLogger(__name__)

# feed_type -> actor lookup. Must match sources.feed_type enum (migration 001).
# 'custom' wired by quick task 260425-ovt — HTML-scrape sources reuse the existing
# enum slot and store CSS selectors in sources.scrape_config (migration 017).
_ACTOR_MAP: dict[str, object] = {
    "rss": poll_rss,
    "taxii": poll_taxii,
    "nvd": poll_nvd,
    "custom": poll_html_scrape,
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
 Idempotent via replace_existing=True . Unknown feed_type
 values are skipped with a structured-log WARNING (defence against
 CRUD introducing new types before the scheduler is updated).
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
                    replace_existing=True,  # — prevents duplicate jobs on restart
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

: DELETE publishes {"deleted": [{"feed_type": "...", "source_id": "..."}]}.
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


# ---------------------------------------------------------------------------
# Phase 11: EASM scheduler jobs
# ---------------------------------------------------------------------------


def scan_history_cleanup_job() -> None:
    """Daily 04:00 UTC — keep the BBOT_SCAN_HISTORY_LIMIT most recent scans per project.

    Uses sync psycopg2 connection (APScheduler is sync; matches Phase 2 Plan 07 precedent).
    CASCADE on easm_findings.scan_id removes orphaned findings automatically.
    events.easm_scan_id SET NULL preserves promoted events (L-4 survival contract).
    """
    import psycopg2  # noqa: PLC0415

    from app.config import settings  # noqa: PLC0415

    limit = settings.BBOT_SCAN_HISTORY_LIMIT  # default 5
    pg_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    pg_url = pg_url.replace("+asyncpg", "")
    conn = psycopg2.connect(pg_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM easm_scans s
                WHERE s.id NOT IN (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY started_at DESC) AS rn
                        FROM easm_scans
                    ) ranked
                    WHERE rn <= %s
                )
                """,
                (limit,),
            )
            conn.commit()
        logger.info("easm_scan_history_cleanup_complete limit=%d", limit)
    except Exception as e:  # noqa: BLE001
        logger.warning("easm_scan_history_cleanup_failed error=%s", e)
    finally:
        conn.close()


def dismiss_expiry_sweep_job() -> None:
    """Hourly — findings with dismiss_until < NOW() bounce back to lifecycle_status='new'.

    Handles the case where a user dismissed a finding with a time limit; once the
    dismiss window expires the finding reappears in the EASM findings view.
    """
    import psycopg2  # noqa: PLC0415

    from app.config import settings  # noqa: PLC0415

    pg_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    pg_url = pg_url.replace("+asyncpg", "")
    conn = psycopg2.connect(pg_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE easm_findings
                SET lifecycle_status='new', dismiss_until=NULL
                WHERE lifecycle_status='dismissed'
                  AND dismiss_until IS NOT NULL
                  AND dismiss_until < NOW()
                """
            )
            conn.commit()
        logger.info("easm_dismiss_expiry_sweep_complete")
    except Exception as e:  # noqa: BLE001
        logger.warning("easm_dismiss_expiry_sweep_failed error=%s", e)
    finally:
        conn.close()


def orphan_reaper_job() -> None:
    """Hourly — reap exited intellibird.easm labelled containers and mark stale scans orphaned.

    Delegates to plan 11-04a's bbot_runner.reap_orphan_containers() (sync) and
    reap_orphan_scans() (async — wrapped in asyncio.run).
    """
    import asyncio  # noqa: PLC0415

    from app.services import bbot_runner  # noqa: PLC0415
    from app.database import async_session_factory  # noqa: PLC0415

    removed = bbot_runner.reap_orphan_containers()
    if removed:
        logger.info("easm_orphan_containers_reaped count=%d ids=%s", len(removed), removed)

    async def _run() -> None:
        async with async_session_factory() as db:
            count = await bbot_runner.reap_orphan_scans(db)
            logger.info("easm_orphan_scans_reaped count=%d", count)

    try:
        asyncio.run(_run())
    except Exception as e:  # noqa: BLE001
        logger.warning("easm_orphan_reap_scans_failed error=%s", e)


# ---------------------------------------------------------------------------
# Phase 12: Brand Protection scheduler jobs (BRP-02 / BRP-04 / H-5 / L-3)
# ---------------------------------------------------------------------------


def _brand_sync_pg_url() -> str:
    """Return a sync psycopg2-style URL (strip asyncpg marker)."""
    from app.config import settings  # noqa: PLC0415

    url = settings.DATABASE_URL
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("+asyncpg", "")
    return url


def brand_monitor_tick_job() -> None:
    """Every BRAND_MONITOR_INTERVAL_SECONDS — enqueue a scan_project actor for
    every active (non-archived) project. Pattern mirrors _make_dispatch but
    reads the projects list at tick-time (not at scheduler-start) so newly
    created projects get picked up without a restart.
    """
    import psycopg2  # noqa: PLC0415

    from app.workers.brand import brand_monitor_scan_project  # noqa: PLC0415

    conn = psycopg2.connect(_brand_sync_pg_url())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM projects WHERE archived IS NOT TRUE")
            project_ids = [str(r[0]) for r in cur.fetchall()]
    finally:
        conn.close()

    for pid in project_ids:
        try:
            brand_monitor_scan_project.send(pid)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "brand_monitor_tick_enqueue_failed project_id=%s error=%s", pid, e
            )
    logger.info("brand_monitor_tick_enqueued count=%d", len(project_ids))


def brand_gdpr_purge_job() -> None:
    """Daily 03:00 UTC — delete person-type brand_matches older than
    project.gdpr_person_match_retention_days (BRP-04 / L-3).

    Per-project retention: a JOIN against brand_terms + projects drives the
    age cut-off per match row (differing retention-days settings across
    projects are honoured in a single DELETE).
    """
    import psycopg2  # noqa: PLC0415

    conn = psycopg2.connect(_brand_sync_pg_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM brand_matches
                USING brand_terms, projects
                WHERE brand_matches.brand_term_id = brand_terms.id
                  AND brand_terms.project_id = projects.id
                  AND brand_terms.term_type = 'person'
                  AND brand_matches.first_seen <
                      NOW() - (projects.gdpr_person_match_retention_days::text
                               || ' days')::interval
                """
            )
            deleted = cur.rowcount
            conn.commit()
        logger.info("brand_gdpr_purge_complete deleted=%d", deleted)
    except Exception as e:  # noqa: BLE001
        logger.warning("brand_gdpr_purge_failed error=%s", e)
    finally:
        conn.close()


def brand_noise_downgrade_sweep_job() -> None:
    """Daily 04:30 UTC — auto-downgrade high-noise active terms to watch_only
    (H-5). A term is "noisy" when its brand_matches count in the last 24h
    exceeds settings.BRAND_NOISE_THRESHOLD. Only affects mode='active' terms.
    """
    import psycopg2  # noqa: PLC0415

    from app.config import settings  # noqa: PLC0415

    threshold = settings.BRAND_NOISE_THRESHOLD
    conn = psycopg2.connect(_brand_sync_pg_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE brand_terms
                SET mode = 'watch_only'
                WHERE mode = 'active'
                  AND archived = false
                  AND id IN (
                      SELECT brand_term_id
                      FROM brand_matches
                      WHERE last_seen > NOW() - INTERVAL '24 hours'
                      GROUP BY brand_term_id
                      HAVING COUNT(*) > %s
                  )
                """,
                (threshold,),
            )
            downgraded = cur.rowcount
            conn.commit()
        logger.info(
            "brand_noise_downgrade_sweep_complete threshold=%d downgraded=%d",
            threshold, downgraded,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("brand_noise_downgrade_sweep_failed error=%s", e)
    finally:
        conn.close()


def brand_dismiss_expiry_sweep_job() -> None:
    """Hourly — flip lifecycle_status back to 'new' for dismissed brand_matches
    whose dismiss_until has passed (BRP-04).

    Mirrors Phase 11 easm_findings dismiss_expiry_sweep_job 1:1.
    """
    import psycopg2  # noqa: PLC0415

    conn = psycopg2.connect(_brand_sync_pg_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE brand_matches
                SET lifecycle_status = 'new', dismiss_until = NULL
                WHERE lifecycle_status = 'dismissed'
                  AND dismiss_until IS NOT NULL
                  AND dismiss_until < NOW()
                """
            )
            expired = cur.rowcount
            conn.commit()
        logger.info("brand_dismiss_expiry_sweep_complete expired=%d", expired)
    except Exception as e:  # noqa: BLE001
        logger.warning("brand_dismiss_expiry_sweep_failed error=%s", e)
    finally:
        conn.close()


def register_brand_jobs(scheduler: BlockingScheduler, settings_obj) -> None:  # type: ignore[no-untyped-def]
    """Wire the 4 Phase 12 Brand Protection jobs onto the given scheduler.

    Job IDs (stable — used by tests + ops):
      - brand_monitor_tick               : IntervalTrigger(BRAND_MONITOR_INTERVAL_SECONDS, default 900s)
      - brand_gdpr_purge                 : CronTrigger(hour=3, minute=0, UTC)
      - brand_noise_downgrade_sweep      : CronTrigger(hour=4, minute=30, UTC)
      - brand_dismiss_expiry_sweep       : IntervalTrigger(hours=1)
    """
    interval = int(getattr(settings_obj, "BRAND_MONITOR_INTERVAL_SECONDS", 900))
    scheduler.add_job(
        brand_monitor_tick_job,
        IntervalTrigger(seconds=interval),
        id="brand_monitor_tick",
        replace_existing=True,
    )
    scheduler.add_job(
        brand_gdpr_purge_job,
        CronTrigger(hour=3, minute=0, timezone="UTC"),
        id="brand_gdpr_purge",
        replace_existing=True,
    )
    scheduler.add_job(
        brand_noise_downgrade_sweep_job,
        CronTrigger(hour=4, minute=30, timezone="UTC"),
        id="brand_noise_downgrade_sweep",
        replace_existing=True,
    )
    scheduler.add_job(
        brand_dismiss_expiry_sweep_job,
        IntervalTrigger(hours=1),
        id="brand_dismiss_expiry_sweep",
        replace_existing=True,
    )
    logger.info(
        "scheduler_registered brand_monitor_tick interval=%d + 3 brand maintenance jobs",
        interval,
    )


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="UTC")
    # jobs (preserved)
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
    # archiver job — nightly at 03:00 UTC
    scheduler.add_job(
        archiver_job_wrapper,
        CronTrigger(hour=3, minute=0),
        id="archiver_nightly",
        replace_existing=True,
    )
    # per-source ingest jobs
    try:
        _load_source_jobs(scheduler)
    except Exception as e:  # noqa: BLE001
        logger.warning("scheduler_source_load_failed error=%s", e)
    # MAP-05 — geo backfill one-shot at startup (+30s)
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
    # webhook dispatcher tick (60s interval)
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
    # Plan 06 — live reload listener (daemon thread)
    try:
        _start_reload_listener(scheduler)
    except Exception as e:  # noqa: BLE001
        logger.warning("scheduler_reload_listener_start_failed error=%s", e)
    # Phase 11: EASM retention + dismiss expiry + orphan reaper
    try:
        scheduler.add_job(
            scan_history_cleanup_job,
            CronTrigger(hour=4, minute=0, timezone="UTC"),
            id="easm_scan_history_cleanup",
            replace_existing=True,
        )
        logger.info("scheduler_registered easm_scan_history_cleanup")
    except Exception as e:  # noqa: BLE001
        logger.warning("scheduler_easm_history_cleanup_register_failed error=%s", e)
    try:
        scheduler.add_job(
            dismiss_expiry_sweep_job,
            IntervalTrigger(hours=1),
            id="easm_dismiss_expiry_sweep",
            replace_existing=True,
        )
        logger.info("scheduler_registered easm_dismiss_expiry_sweep")
    except Exception as e:  # noqa: BLE001
        logger.warning("scheduler_easm_dismiss_expiry_register_failed error=%s", e)
    try:
        scheduler.add_job(
            orphan_reaper_job,
            IntervalTrigger(hours=1),
            id="easm_orphan_reaper",
            replace_existing=True,
        )
        logger.info("scheduler_registered easm_orphan_reaper")
    except Exception as e:  # noqa: BLE001
        logger.warning("scheduler_easm_orphan_reaper_register_failed error=%s", e)
    # Phase 12: Brand Protection monitor tick + GDPR + noise downgrade + dismiss expiry
    try:
        from app.config import settings as _brand_settings  # noqa: PLC0415

        register_brand_jobs(scheduler, _brand_settings)
    except Exception as e:  # noqa: BLE001
        logger.warning("scheduler_brand_jobs_register_failed error=%s", e)
    # Phase 16: Continuous monitoring — silence / drift / parse_error checks
    try:
        from app.scheduler.monitoring_jobs import register_monitoring_jobs  # noqa: PLC0415

        register_monitoring_jobs(scheduler)
    except Exception as e:  # noqa: BLE001
        logger.warning("scheduler_monitoring_jobs_register_failed error=%s", e)
    # Phase 17: AI digest / suggestion expiry / nightly rerank
    try:
        from app.scheduler.ai_jobs import register_ai_jobs  # noqa: PLC0415
    except Exception:  # pragma: no cover
        register_ai_jobs = None
    if register_ai_jobs is not None:
        register_ai_jobs(scheduler)
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
