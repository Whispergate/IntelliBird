"""GET /api/jobs/{job_id} - generic async-job status poll.

Used by BackfillButton and IOCBulkImportDialog to track Dramatiq actors.
Redis key format: job:{job_id}:status → JSON {status, ...fields}.
"""
from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.services.redis_client import get_redis

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobStatus(BaseModel):
    status: str
    processed: int | None = None
    total: int | None = None
    inserted: int | None = None
    updated: int | None = None
    skipped: int | None = None
    events_processed: int | None = None
    iocs_inserted: int | None = None
    error: str | None = None


@router.get("/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str) -> JobStatus:
    """Return current status of a background job from Redis."""
    redis = await get_redis()
    raw = await redis.get(f"job:{job_id}:status")
    if raw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="job_status_corrupt")
    return JobStatus(**data)
