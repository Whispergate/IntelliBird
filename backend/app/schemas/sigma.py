"""Pydantic v2 schemas for Sigma Rule Engine endpoints.

compiled_cache is intentionally absent from SigmaRuleRead - it is an internal
JSONB blob (compiled rule representation) that is never returned to API clients.

Schema summary:
  SigmaRuleCreate       - POST /api/admin/sigma-rules body
  SigmaRulePatch        - PATCH /api/admin/sigma-rules/{id} body
  SigmaRuleRead         - response for all rule read endpoints
  SigmaRuleTest         - POST /api/admin/sigma-rules/test request body
  SigmaRuleTestResult   - POST /api/admin/sigma-rules/test response
"""
from __future__ import annotations

import uuid
import datetime

from pydantic import BaseModel


class SigmaRuleCreate(BaseModel):
    """Create a new Sigma rule (global or per-project)."""

    name: str
    content: str
    level: str | None = None
    tags: list[str] | None = None
    enabled: bool = True
    project_id: uuid.UUID | None = None


class SigmaRulePatch(BaseModel):
    """Partial update for a Sigma rule (PATCH endpoint).

    Content update requires re-parse - omitted here; expose in a future plan
    if operators need in-place content editing via the API.
    """

    name: str | None = None
    enabled: bool | None = None
    # content update requires re-parse - expose if needed in future


class SigmaRuleRead(BaseModel):
    """Read-only view of a Sigma rule. compiled_cache is NOT included - internal JSONB."""

    id: uuid.UUID
    name: str
    content: str
    level: str | None = None
    tags: list[str] | None = None
    enabled: bool
    project_id: uuid.UUID | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


class SigmaRuleTest(BaseModel):
    """Request body for POST /api/admin/sigma-rules/test.

    Accepts a raw Sigma rule YAML string and an optional project scope.
    The test endpoint compiles the rule and runs it against recent events
    without persisting anything to the database.
    """

    rule_yaml: str
    project_id: uuid.UUID | None = None


class SigmaRuleTestResult(BaseModel):
    """Response for POST /api/admin/sigma-rules/test.

    Returns the count of matched events and their UUIDs so the operator
    can evaluate rule quality before saving.
    """

    match_count: int
    matched_event_ids: list[uuid.UUID]
