"""Integration test stubs - admin audit log REST API.

Wave 0: all tests are xfail stubs. They will go GREEN when
plan 25-08 ships the GET /api/admin/audit routes.

Coverage:
  AUDIT-03 - Admin-only paginated audit log endpoint with filtering:
             action, resource_type, date range.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.xfail(strict=False, reason="implementation pending -")
async def test_admin_can_list_audit_log():
    """Admin GET /api/admin/audit returns 200 with paginated result.

    Response shape: { items: [...], next_cursor: <str|null> }
    Each item must include: id, action, resource_type, user_sub, occurred_at.
    """
    assert False, "stub - implement after admin audit routes ship"


@pytest.mark.xfail(strict=False, reason="implementation pending -")
async def test_non_admin_gets_403():
    """Lead+ GET /api/admin/audit returns 403 Forbidden.

    The audit log endpoint is restricted to Admin role only.
    A Lead caller must receive a 403, not the audit data.
    """
    assert False, "stub - implement after admin audit routes ship"


@pytest.mark.xfail(strict=False, reason="implementation pending -")
async def test_filter_by_action():
    """GET /api/admin/audit?action=create returns only rows with action='create'.

    After seeding both 'create' and 'update' audit rows, filtering by
    action=create must return only the create rows.
    """
    assert False, "stub - implement after admin audit routes ship"


@pytest.mark.xfail(strict=False, reason="implementation pending -")
async def test_filter_by_resource_type():
    """GET /api/admin/audit?resource_type=actor returns only actor rows.

    After seeding audit rows for both 'actor' and 'campaign' resource types,
    filtering by resource_type=actor must return only actor rows.
    """
    assert False, "stub - implement after admin audit routes ship"


@pytest.mark.xfail(strict=False, reason="implementation pending -")
async def test_filter_by_date_range():
    """GET /api/admin/audit?from_dt=...&to_dt=... returns only rows within the range.

    After seeding audit rows with different timestamps, the date-range filter
    must return only rows where occurred_at is within [from_dt, to_dt].
    """
    assert False, "stub - implement after admin audit routes ship"
