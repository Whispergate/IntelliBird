"""GET /api/admin/ai-jobs — list AI worker queue + per-job status from Redis.

Admin-only operational view. Reads:
  - dramatiq:ai             — pending message IDs (not yet picked up)
  - dramatiq:ai.msgs        — message bodies (hash) for queued jobs
  - ai:job:{job_id}:project — project association (set at enqueue)
  - ai:job:{job_id}:chunks  — SSE chunk list (RPUSH'd by streaming actors)
  - ai:job:{job_id}:done    — completion flag
  - ai:job:{job_id}:cancelled — cancellation flag
  - ai:rerank:in_progress:{project_id} — rerank lock
  - dramatiq:__heartbeats__ — worker liveness ZSET
"""
from __future__ import annotations

import json
import time
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.middleware.auth import require_admin
from app.security.jwt import AuthUser

router = APIRouter(prefix="/admin", tags=["admin"])


class AIQueuedJob(BaseModel):
    message_id: str
    actor_name: str | None
    args: list[str]
    enqueued_at: float | None


class AIStreamingJob(BaseModel):
    job_id: str
    project_id: str | None
    chunk_count: int
    status: Literal["running", "done", "cancelled"]


class AIRerankLock(BaseModel):
    project_id: str
    ttl_seconds: int


class AIJobsResponse(BaseModel):
    queue_depth: int
    queued: list[AIQueuedJob]
    streaming: list[AIStreamingJob]
    rerank_in_progress: list[AIRerankLock]
    workers_alive: int
    server_time_ms: float


@router.get("/ai-jobs", response_model=AIJobsResponse)
async def get_ai_jobs(
    _user: AuthUser = Depends(require_admin),
) -> AIJobsResponse:
    from app.services.redis_client import get_redis  # noqa: PLC0415

    redis = await get_redis()

    queue_ids_raw = await redis.lrange("dramatiq:ai", 0, -1)
    queue_ids = [
        x.decode() if isinstance(x, bytes) else x for x in queue_ids_raw
    ]

    queued: list[AIQueuedJob] = []
    if queue_ids:
        bodies = await redis.hmget("dramatiq:ai.msgs", queue_ids)
        for body in bodies:
            if body is None:
                continue
            try:
                payload = json.loads(
                    body.decode() if isinstance(body, bytes) else body
                )
            except Exception:  # noqa: BLE001
                continue
            ts = payload.get("message_timestamp")
            queued.append(
                AIQueuedJob(
                    message_id=payload.get("message_id", ""),
                    actor_name=payload.get("actor_name"),
                    args=[str(a) for a in (payload.get("args") or [])],
                    enqueued_at=(ts / 1000.0) if isinstance(ts, (int, float)) else None,
                )
            )

    # Discover streaming jobs by scanning ai:job:*:project (one per job).
    streaming: list[AIStreamingJob] = []
    cursor = 0
    seen_jobs: set[str] = set()
    while True:
        cursor, keys = await redis.scan(
            cursor=cursor, match="ai:job:*:project", count=200
        )
        for k in keys:
            ks = k.decode() if isinstance(k, bytes) else k
            parts = ks.split(":")
            if len(parts) != 4:
                continue
            job_id = parts[2]
            seen_jobs.add(job_id)
        if cursor == 0:
            break

    for job_id in seen_jobs:
        proj = await redis.get(f"ai:job:{job_id}:project")
        proj_str = (
            proj.decode() if isinstance(proj, bytes) else proj
        ) if proj else None
        chunk_len = await redis.llen(f"ai:job:{job_id}:chunks")
        is_done = await redis.exists(f"ai:job:{job_id}:done")
        is_cancelled = await redis.exists(f"ai:job:{job_id}:cancelled")
        if is_cancelled:
            status: Literal["running", "done", "cancelled"] = "cancelled"
        elif is_done:
            status = "done"
        else:
            status = "running"
        streaming.append(
            AIStreamingJob(
                job_id=job_id,
                project_id=proj_str,
                chunk_count=int(chunk_len or 0),
                status=status,
            )
        )

    # Rerank locks.
    rerank_locks: list[AIRerankLock] = []
    cursor = 0
    while True:
        cursor, keys = await redis.scan(
            cursor=cursor, match="ai:rerank:in_progress:*", count=200
        )
        for k in keys:
            ks = k.decode() if isinstance(k, bytes) else k
            project_id = ks.split(":")[-1]
            ttl = await redis.ttl(ks)
            rerank_locks.append(
                AIRerankLock(project_id=project_id, ttl_seconds=int(ttl))
            )
        if cursor == 0:
            break

    # Worker heartbeats — count entries fresher than 60s.
    now_ms = time.time() * 1000.0
    hb_pairs = await redis.zrange(
        "dramatiq:__heartbeats__", 0, -1, withscores=True
    )
    workers_alive = sum(1 for _, score in hb_pairs if (now_ms - score) < 60_000)

    return AIJobsResponse(
        queue_depth=len(queued),
        queued=queued,
        streaming=sorted(streaming, key=lambda j: j.status),
        rerank_in_progress=rerank_locks,
        workers_alive=workers_alive,
        server_time_ms=now_ms,
    )
