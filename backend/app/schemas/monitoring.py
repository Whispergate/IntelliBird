"""Pydantic v2 schemas for monitoring configuration — MON-01, MON-02, MON-03.

Exports:
  MonitoringConfig      — per-source monitoring threshold overrides; stored as JSONB in
                          sources.monitoring_config (migration 016). Empty {} uses feed-type
                          defaults resolved by resolve_sla().
  DEFAULT_SLA_BY_FEED_TYPE — feed-type SLA lookup table (seconds until silence alert fires).
  resolve_sla           — resolve effective SLA for a source given its MonitoringConfig and
                          feed_type; returns override if set, else feed-type default.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

# Locked SLA defaults per feed type (seconds). From 16-CONTEXT.md §MON-01.
# taxii/stix: authoritative, high-frequency feeds — alert after 6h silence.
# rss/nvd: lower-cadence feeds — alert after 24h silence.
DEFAULT_SLA_BY_FEED_TYPE: dict[str, int] = {
    "rss": 86400,    # 24 hours
    "taxii": 21600,  # 6 hours
    "nvd": 86400,    # 24 hours
    "stix": 21600,   # 6 hours
}


class MonitoringConfig(BaseModel):
    """Per-source monitoring threshold configuration stored in sources.monitoring_config JSONB.

    All fields are optional. An empty JSON object {} (the column DEFAULT) means
    "use feed_type defaults for all thresholds". Downstream monitoring checks call
    resolve_sla() to obtain the effective SLA rather than reading last_event_sla_seconds
    directly.

    extra="forbid" prevents unknown keys from silently being ignored — any unrecognised
    monitoring_config key stored in the DB will surface as a validation error at read time,
    flagging schema drift early (Pitfall 6 from 16-RESEARCH.md).
    """

    model_config = ConfigDict(extra="forbid")

    # SLA threshold in seconds. None = "use feed_type default from DEFAULT_SLA_BY_FEED_TYPE".
    # Stored as an integer so comparisons against timedelta.total_seconds() are exact.
    last_event_sla_seconds: int | None = None

    # MON-02: z-score thresholds for volume drift detection (locked from 16-CONTEXT.md).
    drift_z_high: float = 3.0
    drift_z_medium: float = 2.0

    # MON-02: minimum baseline guard — no drift alert if source averages fewer than
    # this many events per day (prevents false positives on low-volume sources during
    # the 7-day EWMA learning window).
    min_baseline_events_per_day: int = 10

    # Timestamp of last config edit — used to enforce the 7-day learning window after
    # a config change (drift detection suppressed until now() - last_changed_at > 7d).
    last_changed_at: datetime | None = None


def resolve_sla(cfg: MonitoringConfig, feed_type: str) -> int:
    """Return effective SLA in seconds for the given source config and feed type.

    If cfg.last_event_sla_seconds is set, that value wins unconditionally.
    Otherwise, look up DEFAULT_SLA_BY_FEED_TYPE by feed_type (case-insensitive).
    Unknown feed types fall back to 86400 (24h) — conservative default matches rss/nvd.
    """
    if cfg.last_event_sla_seconds is not None:
        return cfg.last_event_sla_seconds
    return DEFAULT_SLA_BY_FEED_TYPE.get(feed_type.lower(), 86400)
