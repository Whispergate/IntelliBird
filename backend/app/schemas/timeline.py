"""Pydantic v2 schemas for timeline API — Phase 33 / TIMELINE-01, TIMELINE-02."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class BucketRow(BaseModel):
    """One time bucket in the stacked area chart series.

    ts: ISO-8601 timestamp of bucket start.
    counts_by_tag: mapping of tag name → event count within this bucket.
    """

    ts: datetime
    counts_by_tag: dict[str, int]


class TimelineSeriesResponse(BaseModel):
    """GET /api/projects/{id}/timeline/series response.

    buckets: ordered list of time buckets (oldest first).
    tags: top-10 tags by total event count across all buckets.
    bucket_interval: 'hour' | 'day' | 'week' — adaptive bucket size used.
    """

    buckets: list[BucketRow]
    tags: list[str]
    bucket_interval: str  # 'hour' | 'day' | 'week'


class HeatmapCell(BaseModel):
    """One cell in the hour-of-day × day-of-week heatmap.

    hour: 0–23 (UTC hour of day)
    dow: 0–6 (0=Monday, 6=Sunday — ISO weekday - 1)
    count: number of events in this hour/dow combination
    """

    hour: int
    dow: int
    count: int


class TimelineHeatmapResponse(BaseModel):
    """GET /api/projects/{id}/timeline/heatmap response.

    cells: exactly 168 cells covering all (hour, dow) combinations.
    Cells with no events have count=0.
    """

    cells: list[HeatmapCell]
