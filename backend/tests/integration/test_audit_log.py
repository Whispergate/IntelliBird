"""Integration test stubs — service-layer audit logging.

Phase 25 Wave 0: all tests are xfail stubs. They will go GREEN when
plan 25-07 ships the audit log middleware and service layer.

Coverage:
  AUDIT-02 — every mutating operation on actors/campaigns writes an audit_log
             row with action, resource_type, user_sub, request_id, and
             before_jsonb / after_jsonb diff capture.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.xfail(strict=False, reason="implementation pending — Phase 25 plan 25-07")
async def test_create_actor_writes_audit_row():
    """POST /api/actors produces one audit_log row with action='create'.

    After creation:
      SELECT * FROM audit_log
        WHERE action = 'create' AND resource_type = 'actor'
    must return exactly 1 row with non-null user_sub, request_id, and after_jsonb.
    before_jsonb must be NULL for create operations (nothing existed before).
    """
    assert False, "stub — implement after audit log service ships"


@pytest.mark.xfail(strict=False, reason="implementation pending — Phase 25 plan 25-07")
async def test_update_actor_writes_before_after():
    """PATCH /api/actors/{id} produces an audit_log row with both before and after snapshots.

    After update:
      SELECT before_jsonb, after_jsonb FROM audit_log
        WHERE action = 'update' AND resource_type = 'actor'
    must return a row where BOTH before_jsonb and after_jsonb are non-null.
    The diff between them must reflect the patched field values.
    """
    assert False, "stub — implement after audit log service ships"


@pytest.mark.xfail(strict=False, reason="implementation pending — Phase 25 plan 25-07")
async def test_delete_campaign_writes_audit_row():
    """DELETE /api/campaigns/{id} produces an audit_log row with action='delete'.

    After deletion:
      SELECT action, resource_type FROM audit_log
        WHERE resource_type = 'campaign' AND action = 'delete'
    must return exactly 1 row. before_jsonb must capture the deleted row;
    after_jsonb must be NULL for delete operations.
    """
    assert False, "stub — implement after audit log service ships"
