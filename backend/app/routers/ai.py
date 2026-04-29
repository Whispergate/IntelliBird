"""/api AI router — Phase 17 / AI-02, AI-03, AI-06, AI-07.

Endpoints:
  POST   /api/events/{event_id}/ai/summarise       — enqueue AI summary job (Analyst+)
  GET    /api/ai/jobs/{job_id}/stream              — SSE token stream from Redis buffer
  GET    /api/events/{event_id}/ai/suggestions     — list suggestions for event (member)
  POST   /api/ai/suggestions/{suggestion_id}/confirm   — confirm single suggestion (Analyst+)
  POST   /api/ai/suggestions/{suggestion_id}/discard   — discard single suggestion (Analyst+)
  POST   /api/projects/{project_id}/ai/suggestions/bulk-confirm  — bulk confirm (Analyst+)
  POST   /api/projects/{project_id}/ai/suggestions/bulk-discard  — bulk discard (Analyst+)
  GET    /api/projects/{project_id}/ai/digest      — latest digest row (member)
  POST   /api/projects/{project_id}/ai/digest/trigger — enqueue digest job (Admin)

SSE buffering contract (RESEARCH.md §Pitfall 6):
  StreamingResponse with Cache-Control: no-cache, X-Accel-Buffering: no.

Token budget (CONTEXT.md §Token budget):
  Pre-flight: check_and_reserve_budget returns 429 with Retry-After header.
  Post-flight: record_actual_tokens adjusts the counter after completion.

PROD-01 scope guard:
  All multi-suggestion endpoints verify suggestion.project_id == project_id
  from the URL path before applying any mutation.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_auth
from app.models.ai import AISuggestion, AISummary
from app.models.events import Event
from app.models.projects import Project, ProjectMembership, ProjectRole
from app.schemas.ai import (
    AISummariseResponse,
    AISuggestionBulkRequest,
    AISuggestionRead,
    AIDigestResponse,
)
from app.security.jwt import AuthUser
from app.security.project_membership import require_project_membership

log = logging.getLogger(__name__)

router = APIRouter(tags=["ai"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ANALYST_ROLES = {ProjectRole.Lead.value, ProjectRole.Contributor.value}


def _seconds_until_utc_midnight() -> int:
    """Seconds remaining until 00:00:00 UTC."""
    from app.services.llm.token_budget import seconds_until_utc_midnight  # noqa: PLC0415
    return seconds_until_utc_midnight()


def _next_midnight_iso() -> str:
    """ISO-8601 string for 00:00:00 UTC tomorrow."""
    from datetime import timedelta  # noqa: PLC0415
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tomorrow.isoformat()


# ---------------------------------------------------------------------------
# POST /api/events/{event_id}/ai/summarise
# ---------------------------------------------------------------------------


@router.post("/events/{event_id}/ai/summarise", status_code=202)
async def enqueue_summarise(
    event_id: uuid.UUID,
    request: Request,
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> AISummariseResponse:
    """Enqueue ai_summarise_event actor and return job_id within 200ms.

    Auth: Analyst (Contributor+) on the project that owns the event.
    Budget gate: 429 with Retry-After / X-Budget-Reset-At when cap exceeded.
    """
    from app.services.llm.token_budget import (  # noqa: PLC0415
        check_and_reserve_budget,
    )
    from app.workers.ai import ai_summarise_event  # noqa: PLC0415

    # 1. Load event to resolve project_id.
    event_row: Event | None = (
        await db.execute(select(Event).where(Event.id == event_id))
    ).scalar_one_or_none()
    if event_row is None:
        raise HTTPException(status_code=404, detail="event_not_found")

    project_id = event_row.project_id

    # 2. Membership guard — Contributor (Analyst) or higher required.
    if user.role != "Admin":
        pid_str = str(project_id)
        cached_rank = user.project_memberships.get(pid_str, 0)
        if cached_rank < 2:  # Contributor=2
            # DB fallback if token was truncated.
            if not user.pm_truncated or cached_rank == 0:
                row = (await db.execute(
                    select(ProjectMembership.project_role).where(
                        ProjectMembership.user_sub == user.id,
                        ProjectMembership.project_id == project_id,
                    )
                )).scalar_one_or_none()
                if row is None or ProjectRole(row) == ProjectRole.Observer:
                    raise HTTPException(
                        status_code=403,
                        detail="requires at least Contributor role for AI summarise",
                    )

    # 3. Load project for token cap.
    project_row: Project | None = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project_row is None:
        raise HTTPException(status_code=404, detail="project_not_found")

    # 4. Estimate tokens (simple heuristic — 1.2× applied in actor; use flat estimate here).
    estimated_tokens = 200  # Pre-flight placeholder before the actor runs litellm.token_counter

    # 5. Budget gate.
    cap = project_row.ai_daily_token_cap or 100_000
    try:
        from app.services.redis_client import get_redis  # noqa: PLC0415
        redis = await get_redis()
        allowed, used = await check_and_reserve_budget(redis, str(project_id), estimated_tokens, cap)
    except Exception as budget_exc:  # noqa: BLE001
        log.warning("budget_check_failed event_id=%s error=%r", event_id, budget_exc)
        allowed = True  # Degrade gracefully — do not block on Redis error.
        used = 0
        redis = None  # type: ignore[assignment]

    if not allowed:
        retry_after = _seconds_until_utc_midnight()
        reset_at = _next_midnight_iso()
        return JSONResponse(  # type: ignore[return-value]
            status_code=429,
            content={
                "detail": "daily budget exhausted",
                "used": used,
                "cap": cap,
                "reset_at": reset_at,
            },
            headers={
                "Retry-After": str(retry_after),
                "X-Budget-Reset-At": reset_at,
            },
        )

    # 6. Generate job_id; store project association in Redis for stream auth.
    job_id = str(uuid.uuid4())
    try:
        if redis is not None:
            await redis.set(f"ai:job:{job_id}:project", str(project_id), ex=3600)
    except Exception as exc:  # noqa: BLE001
        log.warning("job_project_key_set_failed job_id=%s error=%r", job_id, exc)

    # 7. Enqueue.
    ai_summarise_event.send(job_id, str(event_id), str(project_id))
    log.info("ai_summarise_enqueued job_id=%s event_id=%s project_id=%s", job_id, event_id, project_id)

    return AISummariseResponse(job_id=job_id)


# ---------------------------------------------------------------------------
# GET /api/ai/jobs/{job_id}/stream — SSE
# ---------------------------------------------------------------------------


async def _sse_generator(
    job_id: str,
    request: Request,
) -> AsyncGenerator[str, None]:
    """Replay Redis chunk list as SSE events until done or client disconnect."""
    from app.services.redis_client import get_redis  # noqa: PLC0415

    chunk_key = f"ai:job:{job_id}:chunks"
    cancel_key = f"ai:job:{job_id}:cancelled"
    done_key = f"ai:job:{job_id}:done"

    try:
        redis = await get_redis()
    except Exception as exc:
        log.error("sse_redis_connect_failed job_id=%s error=%r", job_id, exc)
        yield "event: error\ndata: redis_unavailable\n\n"
        return

    sent = 0
    while True:
        # Check client disconnect.
        if await request.is_disconnected():
            try:
                await redis.set(cancel_key, "1", ex=300)
            except Exception:  # noqa: BLE001
                pass
            log.info("sse_client_disconnected job_id=%s sent=%d", job_id, sent)
            break

        # Drain new chunks since last position.
        try:
            chunks = await redis.lrange(chunk_key, sent, -1)
        except Exception as exc:  # noqa: BLE001
            log.warning("sse_lrange_failed job_id=%s error=%r", job_id, exc)
            yield f"event: error\ndata: {exc!s}\n\n"
            break

        for chunk in chunks:
            chunk_text = chunk.decode() if isinstance(chunk, bytes) else chunk
            yield f"data: {chunk_text}\n\n"
            sent += 1

        # Check done flag.
        try:
            is_done = await redis.exists(done_key)
        except Exception:  # noqa: BLE001
            is_done = False

        if is_done:
            yield "event: done\ndata: {}\n\n"
            break

        await asyncio.sleep(0.05)


@router.get("/ai/jobs/{job_id}/stream")
async def stream_job(
    job_id: str,
    request: Request,
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """SSE endpoint — replays Redis chunk list until job is done.

    Auth: authenticated user that is a member of the project associated with job_id.
    The project association is stored in ai:job:{job_id}:project at enqueue time.
    """
    # Verify project membership for the job.
    try:
        from app.services.redis_client import get_redis  # noqa: PLC0415
        redis = await get_redis()
        project_id_bytes = await redis.get(f"ai:job:{job_id}:project")
    except Exception:  # noqa: BLE001
        project_id_bytes = None

    if project_id_bytes is not None:
        project_id_str = project_id_bytes.decode() if isinstance(project_id_bytes, bytes) else project_id_bytes
        project_id = uuid.UUID(project_id_str)
        if user.role != "Admin":
            pid_str = str(project_id)
            cached_rank = user.project_memberships.get(pid_str, 0)
            if cached_rank == 0:
                # Check DB if pm is truncated, else reject.
                if not user.pm_truncated:
                    raise HTTPException(status_code=403, detail="not a project member")
                row = (await db.execute(
                    select(ProjectMembership.project_role).where(
                        ProjectMembership.user_sub == user.id,
                        ProjectMembership.project_id == project_id,
                    )
                )).scalar_one_or_none()
                if row is None:
                    raise HTTPException(status_code=403, detail="not a project member")

    return StreamingResponse(
        _sse_generator(job_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# GET /api/events/{event_id}/ai/suggestions
# ---------------------------------------------------------------------------


@router.get("/events/{event_id}/ai/suggestions", response_model=list[AISuggestionRead])
async def list_suggestions(
    event_id: uuid.UUID,
    status: str | None = Query(default=None),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> list[AISuggestionRead]:
    """Return AI suggestions for an event.

    Auth: project member (any role). Status filter optional: pending/confirmed/discarded.
    """
    # Resolve event → project_id for membership check.
    event_row: Event | None = (
        await db.execute(select(Event).where(Event.id == event_id))
    ).scalar_one_or_none()
    if event_row is None:
        raise HTTPException(status_code=404, detail="event_not_found")

    # Membership check.
    if user.role != "Admin":
        pid_str = str(event_row.project_id)
        cached_rank = user.project_memberships.get(pid_str, 0)
        if cached_rank == 0:
            if not user.pm_truncated:
                raise HTTPException(status_code=403, detail="not a project member")
            row = (await db.execute(
                select(ProjectMembership.project_role).where(
                    ProjectMembership.user_sub == user.id,
                    ProjectMembership.project_id == event_row.project_id,
                )
            )).scalar_one_or_none()
            if row is None:
                raise HTTPException(status_code=403, detail="not a project member")

    stmt = select(AISuggestion).where(AISuggestion.event_id == event_id)
    if status is not None:
        stmt = stmt.where(AISuggestion.status == status)
    stmt = stmt.order_by(AISuggestion.created_at.asc())
    rows = (await db.execute(stmt)).scalars().all()
    return [AISuggestionRead.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# POST /api/ai/suggestions/{suggestion_id}/confirm|discard
# ---------------------------------------------------------------------------


async def _transition_suggestion(
    suggestion_id: uuid.UUID,
    new_status: str,
    user: AuthUser,
    db: AsyncSession,
) -> AISuggestionRead:
    """Shared logic for confirm/discard single suggestion."""
    row: AISuggestion | None = (
        await db.execute(select(AISuggestion).where(AISuggestion.id == suggestion_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="suggestion_not_found")

    # Membership check — Contributor+ required.
    if user.role != "Admin":
        pid_str = str(row.project_id)
        cached_rank = user.project_memberships.get(pid_str, 0)
        if cached_rank < 2:  # Contributor=2
            if not user.pm_truncated or cached_rank == 0:
                mem_row = (await db.execute(
                    select(ProjectMembership.project_role).where(
                        ProjectMembership.user_sub == user.id,
                        ProjectMembership.project_id == row.project_id,
                    )
                )).scalar_one_or_none()
                if mem_row is None or ProjectRole(mem_row) == ProjectRole.Observer:
                    raise HTTPException(status_code=403, detail="requires at least Contributor")

    now = datetime.now(timezone.utc)
    row.status = new_status
    row.decided_at = now
    try:
        row.decided_by_user_id = uuid.UUID(user.id)
    except (ValueError, AttributeError):
        row.decided_by_user_id = None
    await db.commit()
    await db.refresh(row)
    return AISuggestionRead.model_validate(row)


@router.post("/ai/suggestions/{suggestion_id}/confirm", response_model=AISuggestionRead)
async def confirm_suggestion(
    suggestion_id: uuid.UUID,
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> AISuggestionRead:
    """Confirm a single AI suggestion. Requires Contributor+ on its project."""
    return await _transition_suggestion(suggestion_id, "confirmed", user, db)


@router.post("/ai/suggestions/{suggestion_id}/discard", response_model=AISuggestionRead)
async def discard_suggestion(
    suggestion_id: uuid.UUID,
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> AISuggestionRead:
    """Discard a single AI suggestion. Requires Contributor+ on its project."""
    return await _transition_suggestion(suggestion_id, "discarded", user, db)


# ---------------------------------------------------------------------------
# POST /api/projects/{project_id}/ai/suggestions/bulk-confirm|bulk-discard
# ---------------------------------------------------------------------------


async def _bulk_transition(
    project_id: uuid.UUID,
    body: AISuggestionBulkRequest,
    new_status: str,
    user: AuthUser,
    db: AsyncSession,
) -> list[AISuggestionRead]:
    """Bulk confirm or discard suggestions.

    PROD-01 guard: all ids must belong to project_id.
    """
    # All ids must belong to this project.
    rows = (
        await db.execute(
            select(AISuggestion).where(
                AISuggestion.id.in_(body.ids),
                AISuggestion.project_id == project_id,
            )
        )
    ).scalars().all()

    found_ids = {r.id for r in rows}
    missing = [str(i) for i in body.ids if i not in found_ids]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"suggestions not found or not in project: {missing}",
        )

    now = datetime.now(timezone.utc)
    try:
        decider_id: uuid.UUID | None = uuid.UUID(user.id)
    except (ValueError, AttributeError):
        decider_id = None

    for row in rows:
        row.status = new_status
        row.decided_at = now
        row.decided_by_user_id = decider_id

    await db.commit()
    for row in rows:
        await db.refresh(row)
    return [AISuggestionRead.model_validate(r) for r in rows]


@router.post(
    "/projects/{project_id}/ai/suggestions/bulk-confirm",
    response_model=list[AISuggestionRead],
)
async def bulk_confirm_suggestions(
    project_id: uuid.UUID,
    body: AISuggestionBulkRequest,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Contributor)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> list[AISuggestionRead]:
    """Bulk-confirm AI suggestions. Contributor+ on project required."""
    return await _bulk_transition(project_id, body, "confirmed", user, db)


@router.post(
    "/projects/{project_id}/ai/suggestions/bulk-discard",
    response_model=list[AISuggestionRead],
)
async def bulk_discard_suggestions(
    project_id: uuid.UUID,
    body: AISuggestionBulkRequest,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Contributor)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> list[AISuggestionRead]:
    """Bulk-discard AI suggestions. Contributor+ on project required."""
    return await _bulk_transition(project_id, body, "discarded", user, db)


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/ai/digest
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/ai/digest", response_model=AIDigestResponse)
async def get_digest(
    project_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    db: AsyncSession = Depends(get_session),
) -> AIDigestResponse:
    """Return the latest ai_summaries row with summary_type='digest' for this project.

    Returns 404 when no digest has been generated yet.
    """
    row: AISummary | None = (
        await db.execute(
            select(AISummary)
            .where(
                AISummary.project_id == project_id,
                AISummary.summary_type == "digest",
            )
            .order_by(AISummary.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="no_digest_available")

    return AIDigestResponse.model_validate(row)


# ---------------------------------------------------------------------------
# POST /api/projects/{project_id}/ai/digest/trigger
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/ai/digest/trigger", status_code=202)
async def trigger_digest(
    project_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    user: AuthUser = Depends(require_auth),
) -> dict:
    """Enqueue ai_digest_project actor. Admin (Lead via bypass) only.

    Returns 202 with {queued: true, project_id}.
    """
    from app.workers.ai import ai_digest_project  # noqa: PLC0415

    ai_digest_project.send(str(project_id))
    log.info("ai_digest_triggered project_id=%s by=%s", project_id, user.id)
    return {"queued": True, "project_id": str(project_id)}
