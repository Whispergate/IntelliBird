"""Admin Monitoring Dashboard API — MON-04, Phase 16.

Endpoints:
  GET  /api/admin/monitoring/sources  — Dashboard table data: per-source health
       metrics including silence SLA breach status, parse error rate, drift z-score,
       and a 168-bucket hourly sparkline.
  PATCH /api/admin/monitoring/sources/{source_id} — Update per-source monitoring
       config JSONB. Sets last_changed_at = now() to restart the 7-day learning window.

All endpoints require Admin role (Depends(require_admin) — 403 for non-admin).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_admin
from app.schemas.monitoring import DEFAULT_SLA_BY_FEED_TYPE, MonitoringConfig, resolve_sla
from app.security.jwt import AuthUser

router = APIRouter(prefix="/admin/monitoring", tags=["admin"])


# ---------------------------------------------------------------------------
# GET /api/admin/monitoring/sources
# ---------------------------------------------------------------------------


@router.get("/sources")
async def list_monitoring_sources(
    _admin: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Return per-source monitoring health metrics for the admin dashboard.

    Response shape per source:
      id, name, feed_type, last_event_at, silence_sla_seconds, sla_breached (bool),
      silent_failure_count, parse_error_rate_1h (float 0-1), drift_z_score (float|None),
      drift_severity (str|None), sparkline ([int]*168 — hourly event counts, last 7d)
    """
    now = datetime.now(timezone.utc)

    # --- Base source query ---------------------------------------------------
    sources_result = await db.execute(
        text(
            "SELECT id, name, feed_type, last_event_at, monitoring_config, "
            "       silent_failure_count, created_at "
            "FROM sources "
            "WHERE enabled = true "
            "ORDER BY name"
        )
    )
    sources = sources_result.mappings().all()

    if not sources:
        return []

    source_ids = [str(row["id"]) for row in sources]

    # --- Parse error rate for last 1h (aggregate across all sources) ---------
    parse_result = await db.execute(
        text(
            "SELECT source_id, "
            "  COALESCE(SUM(parse_ok), 0)    AS po, "
            "  COALESCE(SUM(parse_error), 0) AS pe "
            "FROM source_ingest_stats_hourly "
            "WHERE source_id = ANY(:ids) "
            "  AND bucket >= now() - INTERVAL '1 hour' "
            "GROUP BY source_id"
        ),
        {"ids": source_ids},
    )
    parse_by_source: dict[str, dict] = {}
    for r in parse_result.mappings().all():
        parse_by_source[str(r["source_id"])] = {
            "po": int(r["po"]),
            "pe": int(r["pe"]),
        }

    # --- Sparkline: last 168 hourly buckets (7d) per source ------------------
    sparkline_result = await db.execute(
        text(
            "SELECT source_id, bucket, "
            "  (parse_ok + parse_error) AS total "
            "FROM source_ingest_stats_hourly "
            "WHERE source_id = ANY(:ids) "
            "  AND bucket >= now() - INTERVAL '7 days' "
            "ORDER BY source_id, bucket"
        ),
        {"ids": source_ids},
    )
    sparkline_by_source: dict[str, list[int]] = {}
    for r in sparkline_result.mappings().all():
        sid = str(r["source_id"])
        sparkline_by_source.setdefault(sid, []).append(int(r["total"]))

    # --- Drift z-score: compute from last 168 buckets per source -------------
    from app.services.monitoring.drift import (  # noqa: PLC0415
        compute_z_score,
        classify_severity,
        is_in_learning_window,
        MIN_BASELINE_POINTS,
    )

    drift_result = await db.execute(
        text(
            "SELECT source_id, bucket, "
            "  (parse_ok + parse_error) AS total "
            "FROM source_ingest_stats_hourly "
            "WHERE source_id = ANY(:ids) "
            "  AND bucket >= now() - INTERVAL '7 days' "
            "ORDER BY source_id, bucket"
        ),
        {"ids": source_ids},
    )
    drift_buckets_by_source: dict[str, list] = {}
    for r in drift_result.mappings().all():
        sid = str(r["source_id"])
        drift_buckets_by_source.setdefault(sid, []).append(float(r["total"]))

    # --- Build response rows -------------------------------------------------
    response = []
    for row in sources:
        source_id = str(row["id"])
        feed_type = row["feed_type"] or "rss"

        cfg = MonitoringConfig.model_validate(row["monitoring_config"] or {})
        sla_seconds = resolve_sla(cfg, feed_type)

        last_event_at = row["last_event_at"]
        if last_event_at is not None and last_event_at.tzinfo is None:
            last_event_at = last_event_at.replace(tzinfo=timezone.utc)

        sla_breached = (
            last_event_at is not None
            and (now - last_event_at).total_seconds() > sla_seconds
        )

        # Parse error rate
        pe_data = parse_by_source.get(source_id, {"po": 0, "pe": 0})
        total_parses = pe_data["po"] + pe_data["pe"]
        parse_error_rate_1h = (
            pe_data["pe"] / total_parses if total_parses > 0 else 0.0
        )

        # Drift z-score
        drift_z_score = None
        drift_severity = None
        created_at = row["created_at"]
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if created_at is not None and not is_in_learning_window(
            created_at, cfg.last_changed_at, now
        ):
            buckets = drift_buckets_by_source.get(source_id, [])
            if len(buckets) >= MIN_BASELINE_POINTS + 1:
                hourly = buckets[:-1]
                current = buckets[-1]
                z = compute_z_score(hourly, current)
                drift_z_score = z
                drift_severity = classify_severity(
                    z, z_high=cfg.drift_z_high, z_medium=cfg.drift_z_medium
                )

        sparkline = sparkline_by_source.get(source_id, [])

        response.append(
            {
                "id": source_id,
                "name": row["name"],
                "feed_type": feed_type,
                "last_event_at": last_event_at.isoformat() if last_event_at else None,
                "silence_sla_seconds": sla_seconds,
                "sla_breached": sla_breached,
                "silent_failure_count": row["silent_failure_count"] or 0,
                "parse_error_rate_1h": round(parse_error_rate_1h, 4),
                "drift_z_score": drift_z_score,
                "drift_severity": drift_severity,
                "sparkline": sparkline[-168:],  # at most 168 buckets
            }
        )

    return response


# ---------------------------------------------------------------------------
# PATCH /api/admin/monitoring/sources/{source_id}
# ---------------------------------------------------------------------------


@router.patch("/sources/{source_id}")
async def update_monitoring_config(
    source_id: uuid.UUID,
    payload: MonitoringConfig,
    _admin: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Update per-source monitoring config JSONB.

    Merges the payload (a MonitoringConfig) onto sources.monitoring_config.
    Always sets last_changed_at = now() so the 7-day learning window restarts
    (M-5 drift learning window suppression).

    Returns the updated monitoring_config as stored.
    """
    # Verify source exists
    src_result = await db.execute(
        text("SELECT id FROM sources WHERE id = :sid"),
        {"sid": str(source_id)},
    )
    if src_result.fetchone() is None:
        raise HTTPException(status_code=404, detail="source_not_found")

    now = datetime.now(timezone.utc)
    # Force last_changed_at = now on every PATCH (restarts learning window)
    new_cfg = payload.model_copy(update={"last_changed_at": now})
    cfg_json = new_cfg.model_dump_json()

    await db.execute(
        text(
            "UPDATE sources "
            "SET monitoring_config = :cfg::jsonb "
            "WHERE id = :sid"
        ),
        {"cfg": cfg_json, "sid": str(source_id)},
    )
    await db.commit()

    return new_cfg.model_dump()
