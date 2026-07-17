"""Unit tests for MonitoringConfig Pydantic schema and resolve_sla helper.

MON-01, MON-02.

Tests verify:
  - MonitoringConfig.model_validate({}) returns expected defaults
  - MonitoringConfig.model_validate({"last_event_sla_seconds": 3600}) overrides default
  - resolve_sla returns per-feed-type SLA defaults when no override is set
  - resolve_sla returns the override when last_event_sla_seconds is set
"""
from __future__ import annotations

import pytest

from app.schemas.monitoring import MonitoringConfig, resolve_sla


def test_monitoring_config_defaults() -> None:
    """MonitoringConfig.model_validate({}) returns locked default values."""
    cfg = MonitoringConfig.model_validate({})

    assert cfg.last_event_sla_seconds is None, (
        "last_event_sla_seconds should default to None (use feed_type default)"
    )
    assert cfg.drift_z_high == 3.0, "drift_z_high must be 3.0 (locked from 16-CONTEXT.md)"
    assert cfg.drift_z_medium == 2.0, "drift_z_medium must be 2.0 (locked from 16-CONTEXT.md)"
    assert cfg.min_baseline_events_per_day == 10, (
        "min_baseline_events_per_day must be 10 (locked from 16-CONTEXT.md)"
    )
    assert cfg.last_changed_at is None, "last_changed_at should default to None"


def test_monitoring_config_override_sla() -> None:
    """MonitoringConfig.model_validate({'last_event_sla_seconds': 3600}) overrides default."""
    cfg = MonitoringConfig.model_validate({"last_event_sla_seconds": 3600})
    assert cfg.last_event_sla_seconds == 3600


def test_resolve_sla_feed_type_defaults() -> None:
    """resolve_sla returns per-feed-type defaults when no override set.

    Locked values from 16-CONTEXT.md §MON-02 and DEFAULT_SLA_BY_FEED_TYPE:
      rss   → 86400 (24 hours)
      taxii → 21600 (6 hours)
      nvd   → 86400 (24 hours)
      stix  → 21600 (6 hours)
    """
    cfg = MonitoringConfig.model_validate({})

    assert resolve_sla(cfg, "rss") == 86400, "RSS SLA default should be 86400 (24h)"
    assert resolve_sla(cfg, "taxii") == 21600, "TAXII SLA default should be 21600 (6h)"
    assert resolve_sla(cfg, "nvd") == 86400, "NVD SLA default should be 86400 (24h)"
    assert resolve_sla(cfg, "stix") == 21600, "STIX SLA default should be 21600 (6h)"


def test_resolve_sla_override_wins() -> None:
    """resolve_sla returns last_event_sla_seconds override regardless of feed_type."""
    cfg = MonitoringConfig.model_validate({"last_event_sla_seconds": 3600})

    # Override should beat every feed_type default
    assert resolve_sla(cfg, "rss") == 3600
    assert resolve_sla(cfg, "taxii") == 3600
    assert resolve_sla(cfg, "nvd") == 3600
    assert resolve_sla(cfg, "stix") == 3600
    assert resolve_sla(cfg, "custom") == 3600


def test_resolve_sla_unknown_feed_type_fallback() -> None:
    """resolve_sla falls back to 86400 for unknown feed types."""
    cfg = MonitoringConfig.model_validate({})
    assert resolve_sla(cfg, "unknown_feed") == 86400, (
        "Unknown feed type should fall back to 86400 (24h)"
    )
