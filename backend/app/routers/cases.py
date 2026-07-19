"""Cases REST API - Case Management - CASE-01, CASE-02, CASE-03, CASE-05.

Endpoints:
  GET    /api/projects/{project_id}/cases                         paginated list
  POST   /api/projects/{project_id}/cases                         create case
  GET    /api/projects/{project_id}/cases/{case_id}               get case
  PATCH  /api/projects/{project_id}/cases/{case_id}               update case
  DELETE /api/projects/{project_id}/cases/{case_id}               delete case

  POST   /api/projects/{project_id}/cases/{case_id}/events        attach events (bulk)
  DELETE /api/projects/{project_id}/cases/{case_id}/events/{event_id}  detach event
  GET    /api/projects/{project_id}/cases/{case_id}/events        list attached events

  POST   /api/projects/{project_id}/cases/{case_id}/iocs          attach IOCs (bulk)
  DELETE /api/projects/{project_id}/cases/{case_id}/iocs/{ioc_id} detach IOC
  GET    /api/projects/{project_id}/cases/{case_id}/iocs          list attached IOCs

  GET    /api/projects/{project_id}/cases/{case_id}/activity      audit log entries

  POST   /api/projects/{project_id}/cases/{case_id}/summarise     enqueue AI summarise
  POST   /api/projects/{project_id}/cases/{case_id}/summarise/regenerate  clear + re-enqueue

RBAC:
  Read endpoints  - Observer+
  Write endpoints - Contributor+

CASE-05 mandate: Every query against `cases` MUST include `Case.project_id == project_id`
to prevent cross-project data leakage.
"""
from __future__ import annotations

import uuid
from datetime import timezone
from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.database import get_session
from app.models.audit import AuditLog
from app.models.cases import Case, CaseEvent, CaseIOC
from app.models.projects import ProjectRole
from app.schemas.cases import (
    AttachEventsRequest,
    AttachIOCsRequest,
    CaseActivityRead,
    CaseCreate,
    CaseEventRead,
    CaseIOCRead,
    CaseListResponse,
    CasePatch,
    CaseRead,
)
from app.security.project_membership import require_project_membership
from app.services.audit import log_audit

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/projects/{project_id}/cases", tags=["cases"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_case_or_404(
    db: AsyncSession, project_id: uuid.UUID, case_id: uuid.UUID
) -> Case:
    """Fetch a case scoped to project_id; raise 404 if absent or wrong project."""
    stmt = select(Case).where(
        Case.id == case_id,
        Case.project_id == project_id,  # CASE-05: cross-project scope guard
    )
    case = (await db.execute(stmt)).scalars().first()
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case_not_found")
    return case


# ---------------------------------------------------------------------------
# Case CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=CaseListResponse)
async def list_cases(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    status_filter: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
    assignee_user_sub: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> CaseListResponse:
    """Paginated case list scoped to project_id (CASE-05)."""
    # Base filter - MANDATORY project scope guard (CASE-05)
    base = select(Case).where(Case.project_id == project_id)  # CASE-05 scope guard

    if status_filter is not None:
        base = base.where(Case.status == status_filter)
    if severity is not None:
        base = base.where(Case.severity == severity)
    if assignee_user_sub is not None:
        base = base.where(Case.assignee_user_sub == assignee_user_sub)

    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar_one()

    items_stmt = base.order_by(Case.created_at.desc()).offset(offset).limit(limit)
    items = list((await db.execute(items_stmt)).scalars().all())

    return CaseListResponse(items=items, total=total)  # type: ignore[arg-type]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CaseRead)
async def create_case(
    project_id: uuid.UUID,
    body: CaseCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Contributor)),
) -> Case:
    """Create a new case in the project."""
    case = Case(
        id=uuid.uuid4(),
        project_id=project_id,
        title=body.title,
        status="open",
        severity=body.severity,
        assignee_user_sub=body.assignee_user_sub,
        description=body.description,
    )
    db.add(case)

    user_sub = getattr(request.state.user, "sub", None) or getattr(request.state.user, "id", None)
    request_id = getattr(request.state, "correlation_id", None)
    log_audit(
        db,
        action="create",
        resource_type="case",
        resource_id=str(case.id),
        user_sub=user_sub,
        request_id=request_id,
        project_id=project_id,
        after={"title": body.title},
    )

    await db.commit()
    await db.refresh(case)
    log.info("case_created", case_id=str(case.id), project_id=str(project_id), user_sub=user_sub)
    return case


@router.get("/{case_id}", response_model=CaseRead)
async def get_case(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
) -> Case:
    """Fetch single case - scoped to project_id (CASE-05)."""
    return await _get_case_or_404(db, project_id, case_id)


@router.patch("/{case_id}", response_model=CaseRead)
async def patch_case(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    body: CasePatch,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Contributor)),
) -> Case:
    """Update case fields. Automatically sets closed_at when status → resolved/closed."""
    case = await _get_case_or_404(db, project_id, case_id)

    before: dict = {
        "title": case.title,
        "status": case.status,
        "severity": case.severity,
        "assignee_user_sub": case.assignee_user_sub,
        "description": case.description,
        "summary_md": case.summary_md,
        "closed_at": case.closed_at.isoformat() if case.closed_at else None,
    }

    old_status = case.status
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(case, field, value)

    # Auto-set closed_at when transitioning to resolved/closed
    new_status = case.status
    if new_status in ("resolved", "closed") and case.closed_at is None:
        case.closed_at = datetime.now(tz=timezone.utc)

    after: dict = {
        "title": case.title,
        "status": case.status,
        "severity": case.severity,
        "assignee_user_sub": case.assignee_user_sub,
        "description": case.description,
        "summary_md": case.summary_md,
        "closed_at": case.closed_at.isoformat() if case.closed_at else None,
    }

    action = "status_changed" if "status" in update_data and old_status != new_status else "update"

    user_sub = getattr(request.state.user, "sub", None) or getattr(request.state.user, "id", None)
    request_id = getattr(request.state, "correlation_id", None)
    log_audit(
        db,
        action=action,
        resource_type="case",
        resource_id=str(case.id),
        user_sub=user_sub,
        request_id=request_id,
        project_id=project_id,
        before=before,
        after=after,
    )

    await db.commit()
    await db.refresh(case)
    log.info("case_updated", case_id=str(case.id), action=action, fields=list(update_data.keys()))
    return case


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_case(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Contributor)),
) -> None:
    """Delete a case (cascade deletes CaseEvent + CaseIOC rows)."""
    case = await _get_case_or_404(db, project_id, case_id)

    user_sub = getattr(request.state.user, "sub", None) or getattr(request.state.user, "id", None)
    request_id = getattr(request.state, "correlation_id", None)
    log_audit(
        db,
        action="delete",
        resource_type="case",
        resource_id=str(case.id),
        user_sub=user_sub,
        request_id=request_id,
        project_id=project_id,
        before={"title": case.title, "status": case.status},
    )

    await db.delete(case)
    await db.commit()
    log.info("case_deleted", case_id=str(case_id), project_id=str(project_id))


# ---------------------------------------------------------------------------
# Evidence: Events
# ---------------------------------------------------------------------------


@router.post("/{case_id}/events", response_model=dict)
async def attach_events(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    body: AttachEventsRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Contributor)),
) -> dict:
    """Bulk-attach events to a case. Idempotent - skips already-attached event_ids."""
    case = await _get_case_or_404(db, project_id, case_id)  # CASE-05 scope guard

    user_sub = getattr(request.state.user, "sub", None) or getattr(request.state.user, "id", None)

    attached_count = 0
    for event_id in body.event_ids:
        exists_stmt = select(CaseEvent).where(
            CaseEvent.case_id == case.id,
            CaseEvent.event_id == event_id,
        )
        existing = (await db.execute(exists_stmt)).scalars().first()
        if existing is None:
            db.add(CaseEvent(case_id=case.id, event_id=event_id, attached_by=user_sub))
            attached_count += 1

    request_id = getattr(request.state, "correlation_id", None)
    log_audit(
        db,
        action="event_attached",
        resource_type="case",
        resource_id=str(case.id),
        user_sub=user_sub,
        request_id=request_id,
        project_id=project_id,
        after={"event_ids": [str(e) for e in body.event_ids]},
    )

    await db.commit()
    return {"attached": attached_count}


@router.delete("/{case_id}/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def detach_event(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    event_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Contributor)),
) -> None:
    """Detach a single event from a case."""
    case = await _get_case_or_404(db, project_id, case_id)  # CASE-05 scope guard

    stmt = select(CaseEvent).where(
        CaseEvent.case_id == case.id,
        CaseEvent.event_id == event_id,
    )
    link = (await db.execute(stmt)).scalars().first()
    if link is not None:
        await db.delete(link)

    user_sub = getattr(request.state.user, "sub", None) or getattr(request.state.user, "id", None)
    request_id = getattr(request.state, "correlation_id", None)
    log_audit(
        db,
        action="event_detached",
        resource_type="case",
        resource_id=str(case.id),
        user_sub=user_sub,
        request_id=request_id,
        project_id=project_id,
        after={"event_id": str(event_id)},
    )

    await db.commit()


@router.get("/{case_id}/events", response_model=list[CaseEventRead])
async def list_case_events(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[CaseEvent]:
    """List events attached to a case - scoped to project_id (CASE-05)."""
    case = await _get_case_or_404(db, project_id, case_id)  # CASE-05 scope guard

    stmt = (
        select(CaseEvent)
        .where(CaseEvent.case_id == case.id)
        .order_by(CaseEvent.attached_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Evidence: IOCs
# ---------------------------------------------------------------------------


@router.post("/{case_id}/iocs", response_model=dict)
async def attach_iocs(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    body: AttachIOCsRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Contributor)),
) -> dict:
    """Bulk-attach IOCs to a case. Idempotent - skips already-attached ioc_ids."""
    case = await _get_case_or_404(db, project_id, case_id)  # CASE-05 scope guard

    user_sub = getattr(request.state.user, "sub", None) or getattr(request.state.user, "id", None)

    attached_count = 0
    for ioc_id in body.ioc_ids:
        exists_stmt = select(CaseIOC).where(
            CaseIOC.case_id == case.id,
            CaseIOC.ioc_id == ioc_id,
        )
        existing = (await db.execute(exists_stmt)).scalars().first()
        if existing is None:
            db.add(CaseIOC(case_id=case.id, ioc_id=ioc_id, attached_by=user_sub))
            attached_count += 1

    request_id = getattr(request.state, "correlation_id", None)
    log_audit(
        db,
        action="ioc_attached",
        resource_type="case",
        resource_id=str(case.id),
        user_sub=user_sub,
        request_id=request_id,
        project_id=project_id,
        after={"ioc_ids": [str(i) for i in body.ioc_ids]},
    )

    await db.commit()
    return {"attached": attached_count}


@router.delete("/{case_id}/iocs/{ioc_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def detach_ioc(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    ioc_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Contributor)),
) -> None:
    """Detach a single IOC from a case."""
    case = await _get_case_or_404(db, project_id, case_id)  # CASE-05 scope guard

    stmt = select(CaseIOC).where(
        CaseIOC.case_id == case.id,
        CaseIOC.ioc_id == ioc_id,
    )
    link = (await db.execute(stmt)).scalars().first()
    if link is not None:
        await db.delete(link)

    user_sub = getattr(request.state.user, "sub", None) or getattr(request.state.user, "id", None)
    request_id = getattr(request.state, "correlation_id", None)
    log_audit(
        db,
        action="ioc_detached",
        resource_type="case",
        resource_id=str(case.id),
        user_sub=user_sub,
        request_id=request_id,
        project_id=project_id,
        after={"ioc_id": str(ioc_id)},
    )

    await db.commit()


@router.get("/{case_id}/iocs", response_model=list[CaseIOCRead])
async def list_case_iocs(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[CaseIOC]:
    """List IOCs attached to a case - scoped to project_id (CASE-05)."""
    case = await _get_case_or_404(db, project_id, case_id)  # CASE-05 scope guard

    stmt = (
        select(CaseIOC)
        .where(CaseIOC.case_id == case.id)
        .order_by(CaseIOC.attached_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------


@router.get("/{case_id}/activity", response_model=list[CaseActivityRead])
async def get_case_activity(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
) -> list[AuditLog]:
    """Return last 100 audit_log rows for this case - scoped to project_id (CASE-05)."""
    # Verify case belongs to project first (CASE-05 scope guard)
    await _get_case_or_404(db, project_id, case_id)

    stmt = (
        select(AuditLog)
        .where(
            AuditLog.resource_type == "case",
            AuditLog.resource_id == str(case_id),
        )
        .order_by(AuditLog.time.desc())
        .limit(100)
    )
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# AI summarise
# ---------------------------------------------------------------------------


@router.post("/{case_id}/summarise", status_code=status.HTTP_202_ACCEPTED)
async def summarise_case(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Contributor)),
) -> dict:
    """Enqueue AI summarise actor for this case. Returns 202 immediately."""
    case = await _get_case_or_404(db, project_id, case_id)  # CASE-05 scope guard

    # Lazy import - ai_summarise_case is implemented in plan 31-04 (same wave).
    # Module-level import would cause ImportError if cases.py is loaded first.
    from app.workers.ai import ai_summarise_case  # noqa: PLC0415

    ai_summarise_case.send(str(case.id), str(project_id))

    user_sub = getattr(request.state.user, "sub", None) or getattr(request.state.user, "id", None)
    request_id = getattr(request.state, "correlation_id", None)
    log_audit(
        db,
        action="summarised",
        resource_type="case",
        resource_id=str(case.id),
        user_sub=user_sub,
        request_id=request_id,
        project_id=project_id,
    )

    await db.commit()
    log.info("case_summarise_queued", case_id=str(case.id), project_id=str(project_id))
    return {"status": "queued"}


@router.post("/{case_id}/summarise/regenerate", status_code=status.HTTP_202_ACCEPTED)
async def regenerate_case_summary(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Contributor)),
) -> dict:
    """Clear existing summary and re-enqueue AI summarise actor."""
    case = await _get_case_or_404(db, project_id, case_id)  # CASE-05 scope guard

    case.summary_md = None
    await db.commit()

    # Lazy import - ai_summarise_case is implemented in plan 31-04 (same wave).
    # Module-level import would cause ImportError if cases.py is loaded first.
    from app.workers.ai import ai_summarise_case  # noqa: PLC0415

    ai_summarise_case.send(str(case.id), str(project_id))

    log.info("case_summary_regenerate_queued", case_id=str(case.id), project_id=str(project_id))
    return {"status": "queued"}
