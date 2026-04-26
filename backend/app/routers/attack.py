"""GET /api/attack-techniques — ATT&CK technique catalog search.

Any authenticated user may query; no project context needed (global catalog).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_auth
from app.models.attack import AttackTechnique
from app.security.jwt import AuthUser

router = APIRouter(prefix="/attack-techniques", tags=["attack"])


class AttackTechniqueResult(BaseModel):
    technique_id: str
    name: str
    tactic: str | None


@router.get("", response_model=list[AttackTechniqueResult])
async def search_attack_techniques(
    q: Annotated[str, Query(description="Search term for technique ID or name")] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    _user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> list[AttackTechniqueResult]:
    """Search ATT&CK techniques by technique_id or name.

    Returns up to `limit` results (max 50), ordered by technique_id.
    An empty `q` returns no results (avoids dumping the full catalog).
    """
    if not q.strip():
        return []

    pattern = f"%{q.strip()}%"
    stmt = (
        select(AttackTechnique)
        .where(
            or_(
                AttackTechnique.technique_id.ilike(pattern),
                AttackTechnique.name.ilike(pattern),
            )
        )
        .order_by(AttackTechnique.technique_id)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        AttackTechniqueResult(
            technique_id=row.technique_id,
            name=row.name,
            tactic=row.tactic,
        )
        for row in rows
    ]
