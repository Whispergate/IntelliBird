"""
Sigma rule admin CRUD - SIGMA-01/SIGMA-03.
POST /api/admin/sigma-rules       - parse and store a Sigma YAML rule (Admin only)
GET  /api/admin/sigma-rules       - list rules (optional ?project_id, ?enabled filters)
PATCH /api/admin/sigma-rules/{id} - update name/enabled; re-parse if content changed
DELETE /api/admin/sigma-rules/{id} - delete rule
POST /api/admin/sigma-rules/test  - evaluate rule YAML against last 100 events
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_admin
from app.models.sigma_rules import SigmaRule
from app.schemas.sigma import (
    SigmaRuleCreate,
    SigmaRulePatch,
    SigmaRuleRead,
    SigmaRuleTest,
    SigmaRuleTestResult,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/sigma-rules", tags=["admin", "sigma"])


def _parse_sigma_rule_for_save(content: str) -> dict:
    """Parse and validate Sigma YAML; return JSON-safe dict.

    Raises HTTPException(422) if the YAML is invalid.
    """
    from app.services.sigma_engine import _parse_sigma_rule  # noqa: PLC0415

    return _parse_sigma_rule(content)


@router.post(
    "",
    response_model=SigmaRuleRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_sigma_rule(
    body: SigmaRuleCreate,
    db: AsyncSession = Depends(get_session),
) -> SigmaRuleRead:
    compiled = _parse_sigma_rule_for_save(body.content)
    row = SigmaRule(
        name=body.name,
        content=body.content,
        compiled_cache=compiled,
        level=body.level,
        tags=body.tags,
        enabled=body.enabled,
        project_id=body.project_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    log.info("sigma_rule_created id=%s name=%s", row.id, row.name)
    return SigmaRuleRead.model_validate(row)


@router.get(
    "",
    response_model=list[SigmaRuleRead],
    dependencies=[Depends(require_admin)],
)
async def list_sigma_rules(
    project_id: uuid.UUID | None = Query(None),
    enabled: bool | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> list[SigmaRuleRead]:
    stmt = select(SigmaRule)
    if project_id is not None:
        stmt = stmt.where(SigmaRule.project_id == project_id)
    if enabled is not None:
        stmt = stmt.where(SigmaRule.enabled == enabled)
    result = await db.execute(stmt.order_by(SigmaRule.created_at.desc()))
    rows = list(result.scalars().all())
    return [SigmaRuleRead.model_validate(r) for r in rows]


@router.patch(
    "/{rule_id}",
    response_model=SigmaRuleRead,
    dependencies=[Depends(require_admin)],
)
async def patch_sigma_rule(
    rule_id: uuid.UUID,
    body: SigmaRulePatch,
    db: AsyncSession = Depends(get_session),
) -> SigmaRuleRead:
    row = await db.get(SigmaRule, rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Sigma rule not found")
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.name is not None:
        row.name = body.name
    await db.commit()
    await db.refresh(row)
    return SigmaRuleRead.model_validate(row)


@router.delete(
    "/{rule_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
async def delete_sigma_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    row = await db.get(SigmaRule, rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Sigma rule not found")
    await db.delete(row)
    await db.commit()
    log.info("sigma_rule_deleted id=%s", rule_id)


@router.post(
    "/test",
    response_model=SigmaRuleTestResult,
    dependencies=[Depends(require_admin)],
)
async def test_sigma_rule(
    body: SigmaRuleTest,
    db: AsyncSession = Depends(get_session),
) -> SigmaRuleTestResult:
    """Evaluate a Sigma rule YAML against the last 100 events for a project (SIGMA-03 test window)."""
    from app.services.sigma_engine import _parse_sigma_rule, _evaluate_condition  # noqa: PLC0415
    from sigma.rule import SigmaRule as _SigmaRule  # noqa: PLC0415

    # 1. Parse rule - 422 on bad YAML
    try:
        cache_dict = _parse_sigma_rule(body.rule_yaml)
        sigma_rule = _SigmaRule.from_dict(cache_dict)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid Sigma rule: {exc}",
        ) from exc

    # 2. Fetch last 100 events scoped to project_id
    from app.services.events_query import build_events_query, EventsQueryParams  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    params = EventsQueryParams()
    stmt = build_events_query(params, dashboard_roles=None, project_id=body.project_id)
    stmt = stmt.limit(100)
    result = await db.execute(stmt)
    events = list(result.scalars().all())

    # 3. Evaluate each event synchronously
    matched_ids: list[uuid.UUID] = []
    for event in events:
        # Resolve source name asynchronously
        source_name: str | None = None
        if event.source_id is not None:
            sn_result = await db.execute(
                text("SELECT name FROM sources WHERE id = :id"),
                {"id": str(event.source_id)},
            )
            source_name = sn_result.scalar_one_or_none()

        # Build STIX pattern string from raw_stix JSONB
        stix_patterns: list[str] = []
        if event.raw_stix:
            for obj in (event.raw_stix.get("objects") or []):
                pat = obj.get("pattern")
                if pat:
                    stix_patterns.append(pat)

        event_dict = {
            "title": event.title or "",
            "description": event.description or "",
            "tags": event.tags or [],
            "threat_actor": None,
            "raw_stix_pattern": " ".join(stix_patterns),
            "source": source_name or "",
        }

        try:
            if _evaluate_condition(sigma_rule, event_dict):
                matched_ids.append(event.id)
        except Exception:
            pass  # evaluation failure for one event must not abort the test

    return SigmaRuleTestResult(match_count=len(matched_ids), matched_event_ids=matched_ids)
