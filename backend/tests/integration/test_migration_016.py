"""Migration 016 schema verification - scaffold for plan 16-02.

Integration tests verifying that Alembic migration 016 applies the expected
schema changes: source_ingest_stats hypertable, 90d retention policy,
source_ingest_stats_hourly continuous aggregate + refresh policy,
webhook_alert_type_enum extension, sources.last_event_at column,
sources.monitoring_config JSONB column, maintenance_windows table, and the
sentinel project row (project_id 00000000-0000-0000-0000-000000000000).
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest  # noqa: E402

pytestmark = pytest.mark.skip(reason="scaffold - implemented in plan 16-02")


@pytest.mark.asyncio
async def test_retention_policy() -> None:
    """add_retention_policy('source_ingest_stats', '90 days') is present."""
    pass


@pytest.mark.asyncio
async def test_continuous_aggregate_exists() -> None:
    """source_ingest_stats_hourly view and refresh policy exist."""
    pass


@pytest.mark.asyncio
async def test_webhook_alert_type_enum_values() -> None:
    """ENUM contains: source_silence, volume_drift, parse_error_rate."""
    pass


@pytest.mark.asyncio
async def test_sources_last_event_at_column() -> None:
    """sources.last_event_at timestamptz column exists."""
    pass


@pytest.mark.asyncio
async def test_sources_monitoring_config_jsonb() -> None:
    """sources.monitoring_config JSONB column exists."""
    pass


@pytest.mark.asyncio
async def test_maintenance_windows_table_shape() -> None:
    """maintenance_windows table has expected columns: id, start_at, end_at, created_by_user_id, reason, created_at."""
    pass


@pytest.mark.asyncio
async def test_sentinel_project_row() -> None:
    """projects row with id '00000000-0000-0000-0000-000000000000' exists."""
    pass
