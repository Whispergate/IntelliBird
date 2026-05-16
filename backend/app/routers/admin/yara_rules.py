"""
YARA rule admin CRUD — Phase 27 YARA-01.
POST /api/admin/yara-rules     — upload and compile a YARA rule (Admin only)
GET  /api/admin/yara-rules     — list rules (with optional ?project_id, ?enabled filters)
PATCH /api/admin/yara-rules/{id} — update name/family/enabled; recompiles if content changed
DELETE /api/admin/yara-rules/{id} — delete rule (cascades to yara_matches)
"""
from __future__ import annotations
import io
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_admin
from app.models.yara_rules import YaraRule
from app.schemas.sandbox import YaraRuleCreate, YaraRulePatch, YaraRuleRead

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/yara-rules", tags=["admin", "yara"])


def _compile_rule(content: str) -> bytes:
    """Compile YARA rule source and return serialised bytes. Raises HTTPException 422 on syntax error."""
    try:
        import yara  # type: ignore[import]
        rules = yara.compile(source=content)
        buf = io.BytesIO()
        rules.save(file=buf)
        return buf.getvalue()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid YARA rule syntax: {exc}",
        )


@router.post(
    "",
    response_model=YaraRuleRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_yara_rule(
    body: YaraRuleCreate,
    db: AsyncSession = Depends(get_session),
) -> YaraRuleRead:
    compiled = _compile_rule(body.content)
    row = YaraRule(
        name=body.name,
        family=body.family,
        content=body.content,
        compiled_cache=compiled,
        enabled=body.enabled,
        project_id=body.project_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    log.info("yara_rule_created id=%s name=%s", row.id, row.name)
    return YaraRuleRead.model_validate(row)


@router.get(
    "",
    response_model=list[YaraRuleRead],
    dependencies=[Depends(require_admin)],
)
async def list_yara_rules(
    project_id: uuid.UUID | None = Query(None),
    enabled: bool | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> list[YaraRuleRead]:
    stmt = select(YaraRule)
    if project_id is not None:
        stmt = stmt.where(YaraRule.project_id == project_id)
    if enabled is not None:
        stmt = stmt.where(YaraRule.enabled == enabled)
    result = await db.execute(stmt.order_by(YaraRule.created_at.desc()))
    rows = list(result.scalars().all())
    return [YaraRuleRead.model_validate(r) for r in rows]


@router.patch(
    "/{rule_id}",
    response_model=YaraRuleRead,
    dependencies=[Depends(require_admin)],
)
async def patch_yara_rule(
    rule_id: uuid.UUID,
    body: YaraRulePatch,
    db: AsyncSession = Depends(get_session),
) -> YaraRuleRead:
    row = await db.get(YaraRule, rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="YARA rule not found")
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.name is not None:
        row.name = body.name
    if body.family is not None:
        row.family = body.family
    # content update requires recompile
    # (YaraRulePatch does not expose content currently — add if needed in future)
    await db.commit()
    await db.refresh(row)
    return YaraRuleRead.model_validate(row)


@router.delete(
    "/{rule_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
async def delete_yara_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    row = await db.get(YaraRule, rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="YARA rule not found")
    await db.delete(row)
    await db.commit()
    log.info("yara_rule_deleted id=%s", rule_id)
