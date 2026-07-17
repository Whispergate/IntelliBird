"""CIB Clusters router — DISINFO-04.

Exposes GET /api/projects/{project_id}/cib-clusters for the
InfluenceOpsWidget on the Blue team dashboard.
"""
from __future__ import annotations

import uuid
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_session
from app.models.cib_clusters import CibCluster
from app.models.projects import ProjectRole
from app.security.project_membership import require_project_membership

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cib-clusters"])


class CibClusterRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    detected_at: str          # ISO-8601
    member_count: int
    severity: str
    evidence: dict | None

    model_config = {"from_attributes": True}


class CibClustersResponse(BaseModel):
    clusters: list[CibClusterRead]
    total: int


@router.get(
    "/projects/{project_id}/cib-clusters",
    response_model=CibClustersResponse,
)
async def list_cib_clusters(
    project_id: uuid.UUID,
    limit: int = Query(default=5, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
) -> CibClustersResponse:
    """Return the most recent CIB clusters for a project."""
    result = await db.execute(
        select(CibCluster)
        .where(CibCluster.project_id == project_id)
        .order_by(desc(CibCluster.detected_at))
        .limit(limit)
    )
    clusters = result.scalars().all()
    cluster_reads = [
        CibClusterRead(
            id=c.id,
            project_id=c.project_id,
            detected_at=c.detected_at.isoformat(),
            member_count=c.member_count,
            severity=c.severity,
            evidence=c.evidence,
        )
        for c in clusters
    ]
    return CibClustersResponse(clusters=cluster_reads, total=len(cluster_reads))
