"""Timeline API — TIMELINE-01, TIMELINE-02, TIMELINE-03.

Endpoints:
  GET /api/projects/{project_id}/timeline/series   — adaptive-bucket stacked area chart
  GET /api/projects/{project_id}/timeline/heatmap  — hour × day-of-week activity heatmap

Both endpoints enforce project isolation via build_scope_predicate (TIMELINE-03).
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models.events import Event
from app.models.projects import ProjectRole
from app.schemas.timeline import (
    BucketRow,
    HeatmapCell,
    TimelineHeatmapResponse,
    TimelineSeriesResponse,
)
from app.security.project_membership import require_project_membership
from app.services.events_query import EventsQueryParams, build_events_query
from app.services.project_scope import build_scope_predicate, fetch_scope_rows_intel

router = APIRouter(tags=["timeline"])


def _make_timeline_auth():
    """Build auth dependency for timeline endpoints.

    When AUTH_ENABLED=False (dev / unit-test mode) the dependency returns
    ProjectRole.Lead immediately so minimal test apps without AuthMiddleware
    still resolve to 200.

    When AUTH_ENABLED=True the full require_project_membership(Observer) dep
    is returned, which validates JWT + project membership before the handler runs.

    This factory is called at module load time so the correct Depends is wired
    into the router's endpoint signatures.
    """
    if not settings.AUTH_ENABLED:
        async def _dev_bypass() -> ProjectRole:
            return ProjectRole.Lead
        return _dev_bypass
    # Production: real membership gate
    return require_project_membership(ProjectRole.Observer)


_timeline_auth = _make_timeline_auth()


# ---------------------------------------------------------------------------
# Internal query helpers (module-level so tests can patch them)
# ---------------------------------------------------------------------------


async def _query_series_buckets(
    session: AsyncSession,
    project_id: uuid.UUID,
    range_days: int,
    *,
    tag: list[str] | None = None,
    tier: list[str] | None = None,
) -> tuple[list[BucketRow], list[str]]:
    """Execute the GROUP BY bucket query and return (buckets, top_tags).

    Adaptive bucket unit:
      range_days ≤ 7  → 'hour'
      range_days ≤ 90 → 'day'
      else            → 'week'

    Top-10 tags by total count are determined and used to build BucketRow
    objects with counts_by_tag dicts.
    """
    if range_days <= 7:
        bucket_unit = "hour"
    elif range_days <= 90:
        bucket_unit = "day"
    else:
        bucket_unit = "week"

    observed_from = datetime.now(timezone.utc) - timedelta(days=range_days)

    params = EventsQueryParams(
        observed_from=observed_from,
        tag=tag if tag else None,
        tier=tier if tier else None,
    )

    # Fetch scope rows for project isolation (TIMELINE-03)
    scope_rows = await fetch_scope_rows_intel(session, project_id)
    scope_pred = build_scope_predicate(scope_rows) if scope_rows else None

    base_stmt = build_events_query(
        params,
        dashboard_roles=None,
        project_id=project_id,
        scope_predicate=scope_pred,
    )

    # Wrap as CTE and group by (bucket_ts, tag)
    cte = base_stmt.cte("scoped_events")

    bucket_col = sa.func.date_trunc(bucket_unit, cte.c.observed_at).label("bucket_ts")
    tag_col = sa.func.unnest(cte.c.tags).label("tag")
    count_col = sa.func.count().label("cnt")

    agg_stmt = (
        sa.select(bucket_col, tag_col, count_col)
        .group_by(bucket_col, tag_col)
        .order_by(bucket_col)
    )

    rows = (await session.execute(agg_stmt)).all()

    # Compute top-10 tags by total count
    tag_totals: dict[str, int] = defaultdict(int)
    for _, t, cnt in rows:
        if t is not None:
            tag_totals[t] += cnt

    top_tags: list[str] = sorted(tag_totals, key=lambda t: -tag_totals[t])[:10]
    top_tag_set = set(top_tags)

    # Pivot into BucketRow list
    bucket_map: dict[datetime, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for bucket_ts, t, cnt in rows:
        if t is not None and t in top_tag_set:
            bucket_map[bucket_ts][t] += cnt

    buckets: list[BucketRow] = [
        BucketRow(ts=ts, counts_by_tag=dict(counts))
        for ts, counts in sorted(bucket_map.items())
    ]

    return buckets, top_tags


async def _query_heatmap_cells(
    session: AsyncSession,
    project_id: uuid.UUID,
    range_days: int,
    *,
    tag: list[str] | None = None,
) -> list[dict]:
    """Execute the EXTRACT(ISODOW/HOUR) GROUP BY query and return 168 cell dicts.

    dow 0 = Monday (ISODOW 1 - 1), dow 6 = Sunday (ISODOW 7 - 1).
    Missing (hour, dow) combinations are filled with count=0.
    """
    observed_from = datetime.now(timezone.utc) - timedelta(days=range_days)

    params = EventsQueryParams(
        observed_from=observed_from,
        tag=tag if tag else None,
    )

    # Fetch scope rows for project isolation (TIMELINE-03)
    scope_rows = await fetch_scope_rows_intel(session, project_id)
    scope_pred = build_scope_predicate(scope_rows) if scope_rows else None

    base_stmt = build_events_query(
        params,
        dashboard_roles=None,
        project_id=project_id,
        scope_predicate=scope_pred,
    )

    cte = base_stmt.cte("scoped_events_hm")

    dow_col = (
        sa.cast(sa.func.extract("isodow", cte.c.observed_at), sa.Integer) - 1
    ).label("dow")
    hour_col = sa.cast(
        sa.func.extract("hour", cte.c.observed_at), sa.Integer
    ).label("hour")
    count_col = sa.func.count().label("cnt")

    agg_stmt = (
        sa.select(dow_col, hour_col, count_col)
        .group_by(dow_col, hour_col)
    )

    rows = (await session.execute(agg_stmt)).all()

    # Build full 168-cell grid; fill missing with 0
    grid: dict[tuple[int, int], int] = {}
    for dow, hour, cnt in rows:
        grid[(dow, hour)] = cnt

    cells: list[dict] = [
        {"hour": h, "dow": d, "count": grid.get((d, h), 0)}
        for d in range(7)
        for h in range(24)
    ]

    return cells


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/timeline/series", response_model=TimelineSeriesResponse)
async def timeline_series(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
    _role: ProjectRole = Depends(_timeline_auth),
    range_days: int = Query(default=30, ge=1, le=366),
    tag: list[str] | None = Query(default=None),
    tier: list[str] | None = Query(default=None),
) -> TimelineSeriesResponse:
    """Adaptive-bucket stacked area chart series scoped to project_id.

    Bucket unit adapts to range_days:
      ≤ 7  days  → hour
      ≤ 90 days  → day
      > 90 days  → week
    """
    # Compute bucket_interval before delegating to helper
    if range_days <= 7:
        bucket_interval = "hour"
    elif range_days <= 90:
        bucket_interval = "day"
    else:
        bucket_interval = "week"

    buckets, tags = await _query_series_buckets(
        db, project_id, range_days, tag=tag, tier=tier
    )

    return TimelineSeriesResponse(
        buckets=buckets,
        tags=tags,
        bucket_interval=bucket_interval,
    )


@router.get("/timeline/heatmap", response_model=TimelineHeatmapResponse)
async def timeline_heatmap(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
    _role: ProjectRole = Depends(_timeline_auth),
    range_days: int = Query(default=30, ge=1, le=366),
    tag: list[str] | None = Query(default=None),
) -> TimelineHeatmapResponse:
    """Hour-of-day × day-of-week event density heatmap scoped to project_id.

    Returns exactly 168 cells (24 hours × 7 days). Missing combinations get count=0.
    dow=0 is Monday, dow=6 is Sunday (ISO weekday − 1).
    """
    cell_dicts = await _query_heatmap_cells(db, project_id, range_days, tag=tag)
    cells = [HeatmapCell(**c) for c in cell_dicts]
    return TimelineHeatmapResponse(cells=cells)
