"""Integration test stubs - migration 026 threat_actors / campaigns / audit_log schema.

Wave 0: all tests are xfail stubs. They will go GREEN when
plan 25-02 ships migration 026 and the TimescaleDB audit_log hypertable.

Coverage:
  ACTOR-01 - threat_actors + campaigns + campaign_events + actor_event_links tables
  AUDIT-01  - audit_log TimescaleDB hypertable with 365-day retention policy
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.xfail(strict=False, reason="implementation pending -")
async def test_threat_actors_table_exists():
    """After alembic upgrade head, threat_actors has all required columns.

    Expected columns: id, primary_name, aliases, country, motivation,
    sophistication, first_seen, profile_md, mitre_group_id,
    last_bootstrap_at, created_at, updated_at.
    """
    assert False, "stub - implement after migration 026 ships"


@pytest.mark.xfail(strict=False, reason="implementation pending -")
async def test_campaigns_table_exists():
    """After alembic upgrade head, campaigns has all required columns.

    Expected columns: id, name, actor_id, start_date, end_date,
    summary_md, project_id, created_by_user_sub.
    """
    assert False, "stub - implement after migration 026 ships"


@pytest.mark.xfail(strict=False, reason="implementation pending -")
async def test_campaign_events_table_exists():
    """After alembic upgrade head, campaign_events M2M table has all required columns.

    Expected columns: campaign_id, event_id, linked_by_user_sub, linked_at.
    Primary key is composite (campaign_id, event_id).
    """
    assert False, "stub - implement after migration 026 ships"


@pytest.mark.xfail(strict=False, reason="implementation pending -")
async def test_actor_event_links_table_exists():
    """After alembic upgrade head, actor_event_links has all required columns.

    Expected columns: actor_id, event_id, linked_at, linked_by.
    Primary key is composite (actor_id, event_id).
    """
    assert False, "stub - implement after migration 026 ships"


@pytest.mark.xfail(strict=False, reason="implementation pending -")
async def test_audit_log_hypertable():
    """After alembic upgrade head, audit_log is a TimescaleDB hypertable with 365-day retention.

    Validation:
      - SELECT hypertable_name FROM timescaledb_information.hypertables
        WHERE hypertable_name = 'audit_log' returns 1 row.
      - Retention policy is configured for 365 days.
    """
    assert False, "stub - implement after migration 026 ships (requires TimescaleDB extension)"
