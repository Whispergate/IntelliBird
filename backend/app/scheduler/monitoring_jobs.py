"""monitoring scheduler jobs.

Three global jobs (CONTEXT.md locked decision - NOT per-source):
  - silence_check_all       IntervalTrigger(minutes=15)
  - drift_check_all         IntervalTrigger(hours=1)
  - parse_error_check_all   IntervalTrigger(minutes=15)

All jobs use SYNC SQLAlchemy sessions (RESEARCH anti-pattern: never asyncio.run
in APScheduler context). Dispatch path: build_*_event_dict → reuse the existing
canonical-event INSERT helper used by normalise.py → existing webhook fan-out
consumes the row.

Gates (in order):
  1. is_in_learning_window  - drift only
  2. is_maintenance_active  - all jobs (H-7)
  3. is_burst_suppressed_key - all jobs (cap 5/source/hour)
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as SyncSession

from app.services.monitoring_synth import (
    build_silence_event_dict,
    build_drift_event_dict,
    build_parse_error_event_dict,
)
from app.services.monitoring.drift import (
    compute_z_score,
    classify_severity,
    is_in_learning_window,
    MIN_BASELINE_POINTS,
)
from app.services.maintenance import is_maintenance_active
from app.services.scoring.burst import is_burst_suppressed_key, record_dispatch_key
from app.schemas.monitoring import MonitoringConfig, resolve_sla

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BURST_CAP_PER_SOURCE = 5
PARSE_ERROR_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# Session + Redis helpers (sync - mirrors brand jobs pattern from jobs.py)
# ---------------------------------------------------------------------------

def _sync_pg_url() -> str:
    """Return a sync psycopg2-style DATABASE_URL (strip asyncpg marker)."""
    from app.config import settings  # noqa: PLC0415

    url = settings.DATABASE_URL
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("+asyncpg", "")
    return url


@contextmanager
def _sync_session() -> Generator[SyncSession, None, None]:
    """Context manager that opens a short-lived sync SQLAlchemy session."""
    engine = create_engine(_sync_pg_url(), future=True)
    try:
        with SyncSession(engine) as session:
            yield session
    finally:
        engine.dispose()


@contextmanager
def _sync_redis():  # type: ignore[return]
    """Context manager that opens a sync Redis client."""
    import redis as redis_lib  # noqa: PLC0415
    from app.config import settings  # noqa: PLC0415

    r = redis_lib.from_url(settings.REDIS_URL)
    try:
        yield r
    finally:
        r.close()


# ---------------------------------------------------------------------------
# Testability helper - injectable "now" for deterministic tests
# ---------------------------------------------------------------------------

def _get_now() -> datetime:
    """Return current UTC datetime. Patchable in tests."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Canonical event INSERT - reuse normalise._persist_event
# ---------------------------------------------------------------------------

def _persist_canonical_event(session: SyncSession, event_dict: dict) -> None:
    """Insert a monitoring alert into the events table using the existing INSERT path.

    Delegates to app.ingest.normalise._persist_event which handles:
    - ON CONFLICT (source_id, content_hash, observed_at) DO NOTHING (dedup)
    - Score injection (SCR-01)
    - ATT&CK tag rows
    - geo resolution

    Monitoring rows carry source_id=NULL (sentinel/cross-project alert) and
    project_id=SENTINEL_PROJECT_ID. The conflict target (source_id, content_hash,
    observed_at) with source_id=NULL means dedup is on content_hash+observed_at only
    for monitoring rows - acceptable since the hash already encodes source_id.
    """
    from app.ingest.normalise import _persist_event  # noqa: PLC0415

    _persist_event(session, event_dict)


# ---------------------------------------------------------------------------
# Shared dispatch gate
# ---------------------------------------------------------------------------

def _dispatch_event(
    session: SyncSession,
    redis_client: object,
    source_id: str,
    event_dict: dict,
) -> bool:
    """Apply maintenance + burst gates, then INSERT canonical event row.

    Returns True if dispatched, False if suppressed.
    Gate order (CONTEXT.md):
      1. is_maintenance_active - global maintenance window suppresses all alerts
      2. is_burst_suppressed_key - per-source hourly cap (cap=5)
    """
    if is_maintenance_active(session):
        logger.info(
            "monitoring_dispatch_suppressed reason=maintenance source_id=%s", source_id
        )
        return False

    key = f"burst:source:{source_id}:hour"
    if is_burst_suppressed_key(redis_client, key, BURST_CAP_PER_SOURCE):  # type: ignore[arg-type]
        logger.info(
            "monitoring_dispatch_suppressed reason=burst source_id=%s", source_id
        )
        return False

    _persist_canonical_event(session, event_dict)
    record_dispatch_key(redis_client, key)  # type: ignore[arg-type]
    return True


# ---------------------------------------------------------------------------
# Job 1: silence_check_all (IntervalTrigger 15 min)
# ---------------------------------------------------------------------------

def silence_check_all_job() -> None:
    """Iterate active sources; emit silence event when now - last_event_at > resolved SLA.

    Source with last_event_at=None (never emitted) is skipped - treated as
    in-grace until first event arrives. This avoids false alerts on freshly
    added sources.
    """
    now = _get_now()
    with _sync_session() as session, _sync_redis() as redis_client:
        rows = session.execute(
            text(
                "SELECT id, name, feed_type, last_event_at, monitoring_config, created_at "
                "FROM sources WHERE enabled = true"
            )
        ).mappings().all()

        for row in rows:
            last_event_at = row["last_event_at"]
            if last_event_at is None:
                # Never emitted - skip until first event arrives
                continue

            cfg = MonitoringConfig.model_validate(row["monitoring_config"] or {})
            sla_seconds = resolve_sla(cfg, row["feed_type"])

            # Make last_event_at timezone-aware if DB returns naive datetime
            if last_event_at.tzinfo is None:
                last_event_at = last_event_at.replace(tzinfo=timezone.utc)

            if (now - last_event_at).total_seconds() <= sla_seconds:
                continue

            event = build_silence_event_dict(
                source_id=str(row["id"]),
                source_name=row["name"],
                last_event_at=last_event_at,
                sla_seconds=sla_seconds,
                now=now,
            )
            dispatched = _dispatch_event(session, redis_client, str(row["id"]), event)
            if dispatched:
                logger.info(
                    "monitoring_silence_alert_dispatched source_id=%s sla_s=%d",
                    row["id"],
                    sla_seconds,
                )

        session.commit()


# ---------------------------------------------------------------------------
# Job 2: drift_check_all (IntervalTrigger 60 min)
# ---------------------------------------------------------------------------

def drift_check_all_job() -> None:
    """Iterate active sources; for each, query 168h CA, compute z-score, dispatch."""
    now = _get_now()
    with _sync_session() as session, _sync_redis() as redis_client:
        rows = session.execute(
            text(
                "SELECT id, name, monitoring_config, created_at "
                "FROM sources WHERE enabled = true"
            )
        ).mappings().all()

        for row in rows:
            cfg = MonitoringConfig.model_validate(row["monitoring_config"] or {})

            created_at = row["created_at"]
            if created_at is not None and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            last_changed_at = cfg.last_changed_at

            if is_in_learning_window(created_at, last_changed_at, now):
                logger.debug(
                    "drift_check_skipped_learning_window source_id=%s", row["id"]
                )
                continue

            # CA query: last 168 hourly buckets from source_ingest_stats_hourly
            buckets = session.execute(
                text(
                    "SELECT bucket, (parse_ok + parse_error) AS total "
                    "FROM source_ingest_stats_hourly "
                    "WHERE source_id = :sid "
                    "  AND bucket >= now() - INTERVAL '7 days' "
                    "ORDER BY bucket"
                ),
                {"sid": str(row["id"])},
            ).mappings().all()

            if len(buckets) < MIN_BASELINE_POINTS + 1:
                continue

            hourly = [float(b["total"]) for b in buckets[:-1]]
            current = float(buckets[-1]["total"])

            z = compute_z_score(hourly, current)
            severity = classify_severity(
                z,
                z_high=cfg.drift_z_high,
                z_medium=cfg.drift_z_medium,
            )
            if severity is None:
                continue

            baseline_mean = sum(hourly) / len(hourly) if hourly else 0.0
            event = build_drift_event_dict(
                source_id=str(row["id"]),
                source_name=row["name"],
                severity=severity,
                z_score=z,  # type: ignore[arg-type]
                baseline_mean=baseline_mean,
                current_value=current,
                window_bucket=buckets[-1]["bucket"],
            )
            dispatched = _dispatch_event(session, redis_client, str(row["id"]), event)
            if dispatched:
                logger.info(
                    "monitoring_drift_alert_dispatched source_id=%s severity=%s z=%s",
                    row["id"],
                    severity,
                    z,
                )

        session.commit()


# ---------------------------------------------------------------------------
# Job 3: parse_error_check_all (IntervalTrigger 15 min)
# ---------------------------------------------------------------------------

def parse_error_check_all_job() -> None:
    """Iterate active sources; alert when parse_error/(parse_ok+parse_error) > 0.5 in last 1h CA."""
    with _sync_session() as session, _sync_redis() as redis_client:
        rows = session.execute(
            text(
                "SELECT s.id, s.name, "
                "  COALESCE(SUM(h.parse_ok), 0)    AS po, "
                "  COALESCE(SUM(h.parse_error), 0) AS pe, "
                "  MAX(h.bucket)                   AS last_bucket "
                "FROM sources s "
                "LEFT JOIN source_ingest_stats_hourly h "
                "  ON h.source_id = s.id "
                " AND h.bucket >= now() - INTERVAL '1 hour' "
                "WHERE s.enabled = true "
                "GROUP BY s.id, s.name"
            )
        ).mappings().all()

        for row in rows:
            total = (row["po"] or 0) + (row["pe"] or 0)
            if total == 0:
                continue

            rate = row["pe"] / total
            if rate <= PARSE_ERROR_THRESHOLD:
                continue

            window_bucket = row["last_bucket"] or _get_now()
            event = build_parse_error_event_dict(
                source_id=str(row["id"]),
                source_name=row["name"],
                parse_ok=int(row["po"]),
                parse_error=int(row["pe"]),
                window_bucket=window_bucket,
            )
            dispatched = _dispatch_event(session, redis_client, str(row["id"]), event)
            if dispatched:
                logger.info(
                    "monitoring_parse_error_alert_dispatched source_id=%s rate=%.2f",
                    row["id"],
                    rate,
                )

        session.commit()


# ---------------------------------------------------------------------------
# Registration helper - called from build_scheduler() in jobs.py
# ---------------------------------------------------------------------------

def register_monitoring_jobs(scheduler: BlockingScheduler) -> None:
    """Wire the 3 monitoring jobs onto the given scheduler.

    Job IDs (stable - used by tests + ops):
      - monitoring_silence_check_all    : IntervalTrigger(minutes=15)
      - monitoring_drift_check_all      : IntervalTrigger(hours=1)
      - monitoring_parse_error_check_all: IntervalTrigger(minutes=15)
    """
    scheduler.add_job(
        silence_check_all_job,
        IntervalTrigger(minutes=15),
        id="monitoring_silence_check_all",
        replace_existing=True,
    )
    scheduler.add_job(
        drift_check_all_job,
        IntervalTrigger(hours=1),
        id="monitoring_drift_check_all",
        replace_existing=True,
    )
    scheduler.add_job(
        parse_error_check_all_job,
        IntervalTrigger(minutes=15),
        id="monitoring_parse_error_check_all",
        replace_existing=True,
    )
    logger.info(
        "scheduler_registered monitoring_jobs silence=15m drift=60m parse_error=15m"
    )
