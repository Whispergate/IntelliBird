"""POST /api/admin/iocs/backfill — Phase 22 / IOC-07.

Admin-only async backfill trigger. Returns 202 + {job_id} immediately and
enqueues `backfill_iocs_actor` on the `ingest` queue (per RESEARCH Pitfall 6
— a synchronous backfill in the HTTP handler would risk timeouts and
worker starvation on the ~29k-event corpus).

Job status is written to Redis under `job:{job_id}:status`; UI polls.
"""
from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_admin
from app.security.jwt import AuthUser

router = APIRouter(prefix="/admin/iocs", tags=["admin"])


class BackfillEnqueued(BaseModel):
    job_id: str
    project_id: str | None


@router.post("/backfill", status_code=status.HTTP_202_ACCEPTED, response_model=BackfillEnqueued)
async def trigger_ioc_backfill(
    db: Annotated[AsyncSession, Depends(get_session)],
    _admin: AuthUser = Depends(require_admin),
    project_id: uuid.UUID | None = Query(
        default=None,
        description=(
            "Optional — restrict backfill to a single project_id. "
            "Omit for an all-projects sweep (admin global run)."
        ),
    ),
) -> BackfillEnqueued:
    """Enqueue an async backfill. Returns 202 with the job_id.

    NOT a synchronous service call — see RESEARCH Pitfall 6. The actor
    streams progress to Redis under `job:{job_id}:status`; UI polls.
    """
    # Lazy imports — keep module-load cheap and avoid pulling Dramatiq
    # broker deps when this router is merely registered.
    from app.services.redis_client import get_redis  # noqa: PLC0415
    from app.workers.iocs import backfill_iocs_actor  # noqa: PLC0415

    job_id = str(uuid.uuid4())
    redis = await get_redis()
    await redis.set(
        f"job:{job_id}:status",
        json.dumps({"status": "queued"}),
        ex=3600,
    )
    backfill_iocs_actor.send(  # type: ignore[attr-defined]
        job_id, str(project_id) if project_id else None
    )
    return BackfillEnqueued(
        job_id=job_id,
        project_id=str(project_id) if project_id else None,
    )
