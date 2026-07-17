"""/api/projects router — PRJ-01 CRUD + PRJ-05 memberships.

Auth model:
  POST /       Admin OR Analyst (via require_analyst_or_above)
  GET /        any authenticated user (list scoped by membership unless Admin)
  GET /{id}    Observer+ (via require_project_membership)
  PATCH /{id}  Lead+ (via require_project_membership)
  POST /{id}/archive   Lead+
  POST /{id}/restore   Lead+
  DELETE /{id}         disabled — returns 405 (archive is the only deletion path)

Auto-Lead: project creator is inserted into project_memberships as Lead in the same
transaction as the project INSERT. Prevents orphaned projects without Lead.

Legacy sentinel protection: the _legacy project (id=LEGACY_PROJECT_ID) is readable
but PATCH/archive/restore/memberships-write all return 403 with
detail='legacy_project_immutable'.

FORWARD REFERENCE (plan 10-07): plan 10-07 will add a sibling
`compare_router = APIRouter(prefix="/projects/compare")` in this same module for
the PRJ-06 compare endpoint, registered BEFORE `router` in main.py so
`/api/projects/compare` does not collide with `/{project_id}` route below.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, delete as sql_delete, func, select, update as sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_admin, require_analyst_or_above, require_auth
from app.models.projects import (
    LEGACY_PROJECT_ID,
    Project,
    ProjectMembership,
    ProjectRole,
    ProjectScopeRow,
    ProjectSource,
)
from app.models.scoring import EventScoreOverride, ProjectScoringRules
from app.models.sources import Source
from app.schemas.ai import (
    AIProviderRead,
    AIProviderTestResponse,
    AIProviderUpdate,
    AIRerankStatus,
    AttackPathRequest,
    AttackPathResponse,
)
from app.schemas.projects import (
    CompareResponse,
    MembershipCreate,
    MembershipResponse,
    MembershipUpdate,
    ProjectCreate,
    ProjectResponse,
    ProjectSourcesBinding,
    ProjectUpdate,
    ScopeRowCreate,
    ScopeRowResponse,
    ScopeRowUpdate,
    SharedIOCSchema,
)
from app.schemas.easm import EASMGateFlipRequest
from app.schemas.scoring import RescoreStatusResponse, ScoringRulesPayload, ScoringRulesRead
from app.security.jwt import AuthUser, PROJECT_ROLE_RANK
from app.security.project_membership import check_project_membership, require_project_membership
from app.services import project_export as _project_export
from app.services.project_compare import (
    shared_actors,
    shared_techniques,
    shared_iocs,
)
from app.services.project_scope import fetch_scope_rows_intel
from app.services.scope_validators import validate_scope_row_value

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _legacy_guard(project_id: uuid.UUID) -> None:
    """Raise 403 if the project id is the frozen sentinel row."""
    if project_id == LEGACY_PROJECT_ID:
        raise HTTPException(status_code=403, detail="legacy_project_immutable")


async def _hydrate(
    db: AsyncSession, p: Project, *, current_user_sub: str
) -> ProjectResponse:
    """Build ProjectResponse with member_count + creator_is_current_user hydrated."""
    count = (
        await db.execute(
            select(func.count(ProjectMembership.id)).where(
                ProjectMembership.project_id == p.id
            )
        )
    ).scalar_one()
    return ProjectResponse(
        id=p.id,
        name=p.name,
        engagement_type=p.engagement_type,  # type: ignore[arg-type]
        description=p.description,
        created_by=p.created_by,
        archived=p.archived,
        active_scans_authorised=p.active_scans_authorised,
        scope_acknowledgement_text=p.scope_acknowledgement_text,
        active_auth_confirmed_at=p.active_auth_confirmed_at,
        active_auth_confirmed_by=getattr(p, "active_auth_confirmed_by", None),
        created_at=p.created_at,
        updated_at=p.updated_at,
        member_count=int(count),
        creator_is_current_user=(p.created_by == current_user_sub),
    )


# ---------------------------------------------------------------------------
# POST / — create project + auto-Lead membership (atomic)
# ---------------------------------------------------------------------------


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreate,
    user: AuthUser = Depends(require_analyst_or_above),
    db: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    """Create a project and atomically bind the creator as Lead.

    If the project INSERT succeeds but the ProjectMembership INSERT fails, the
    transaction rolls back — prevents orphaned projects without a Lead.
    """
    # Python-side UUID generation for SQLite test compatibility (CONTEXT.md
    # §Established Patterns carry-over from source registry pattern).
    project = Project(
        id=uuid.uuid4(),
        name=body.name,
        engagement_type=body.engagement_type,
        description=body.description,
        created_by=user.id,
        archived=False,
    )
    db.add(project)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="project_name_exists")

    # Atomic auto-Lead membership — same transaction as the project INSERT.
    db.add(
        ProjectMembership(
            user_sub=user.id,
            project_id=project.id,
            project_role=ProjectRole.Lead.value,
            added_by=user.id,
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="auto_lead_conflict")
    await db.refresh(project)
    log.info(
        "project_created",
        project_id=str(project.id),
        created_by=user.id,
        engagement_type=project.engagement_type,
    )
    return await _hydrate(db, project, current_user_sub=user.id)


# ---------------------------------------------------------------------------
# GET / — membership-filtered list
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    include_archived: bool = Query(default=False),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> list[ProjectResponse]:
    """List projects visible to the current user.

    Admin sees ALL projects regardless of membership (CONTEXT.md §Project
    membership model "Global Admin bypass" strong default). Non-Admin sees
    only projects where they hold a membership row.
    """
    stmt = select(Project)
    if not include_archived:
        stmt = stmt.where(Project.archived == False)  # noqa: E712
    if user.role != "Admin":
        member_pids = (
            await db.execute(
                select(ProjectMembership.project_id).where(
                    ProjectMembership.user_sub == user.id
                )
            )
        ).scalars().all()
        if not member_pids:
            return []
        stmt = stmt.where(Project.id.in_(member_pids))
    stmt = stmt.order_by(Project.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [await _hydrate(db, p, current_user_sub=user.id) for p in rows]


# ---------------------------------------------------------------------------
# GET /{id} — project detail
# ---------------------------------------------------------------------------


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    p = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="project_not_found")
    return await _hydrate(db, p, current_user_sub=user.id)


# ---------------------------------------------------------------------------
# PATCH /{id} — update (Lead+ only)
# ---------------------------------------------------------------------------


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    _legacy_guard(project_id)
    p = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="project_not_found")
    if body.name is not None:
        p.name = body.name
    if body.engagement_type is not None:
        p.engagement_type = body.engagement_type
    if body.description is not None:
        p.description = body.description
    if body.archived is not None:
        p.archived = body.archived
    p.updated_at = datetime.now(timezone.utc)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="project_name_exists")
    await db.refresh(p)
    log.info("project_updated", project_id=str(project_id), updated_by=user.id)
    return await _hydrate(db, p, current_user_sub=user.id)


# ---------------------------------------------------------------------------
# POST /{id}/archive + /{id}/restore — soft delete toggles
# ---------------------------------------------------------------------------


@router.post("/{project_id}/archive", response_model=ProjectResponse)
async def archive_project(
    project_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    _legacy_guard(project_id)
    p = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="project_not_found")
    p.archived = True
    p.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(p)
    log.info("project_archived", project_id=str(project_id), archived_by=user.id)
    return await _hydrate(db, p, current_user_sub=user.id)


@router.post("/{project_id}/restore", response_model=ProjectResponse)
async def restore_project(
    project_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    _legacy_guard(project_id)
    p = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="project_not_found")
    p.archived = False
    p.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(p)
    log.info("project_restored", project_id=str(project_id), restored_by=user.id)
    return await _hydrate(db, p, current_user_sub=user.id)


# ---------------------------------------------------------------------------
# EASM active-scan gate (EASM-04 / C-3) — flip + revoke
# ---------------------------------------------------------------------------


def _resolve_project_rank(user: AuthUser, project_id: uuid.UUID) -> int:
    """Return the caller's numeric rank (1=Observer, 2=Contributor, 3=Lead) for the given
    project, using the JWT pm claim cache only.

    Global Admin callers should never reach this helper (they are short-circuited upstream).
    Returns 0 when the user has no membership entry for the project.
    """
    pid_str = str(project_id)
    return user.project_memberships.get(pid_str, 0)


_GATE_AUTHORITY_MSG = (
    "You do not have permission to authorise active scans. "
    "Lead or Admin role required."
)
_GATE_NAME_MISMATCH_MSG = (
    "Scope acknowledgement text does not match the project name."
)
_GATE_LEGACY_MSG = (
    "Authorisation is not available for archived or legacy projects."
)
_LEAD_RANK = PROJECT_ROLE_RANK[ProjectRole.Lead.value]


@router.patch("/{project_id}/easm-gate", response_model=ProjectResponse)
async def flip_easm_gate(
    project_id: uuid.UUID,
    body: EASMGateFlipRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    """Flip active-scan gate ON (EASM-04 / C-3).

    Canonical copy (UI-SPEC §Error states):
    - 403: "You do not have permission to authorise active scans. Lead or Admin role required."
    - 422 (name mismatch): "Scope acknowledgement text does not match the project name."
    - 422 (archived/legacy): "Authorisation is not available for archived or legacy projects."
    """
    user: AuthUser = request.state.user
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="project_not_found")

    # Legacy + archived guards (checked before authority so attacker cannot probe via 403)
    if project.id == LEGACY_PROJECT_ID:
        raise HTTPException(status_code=422, detail=_GATE_LEGACY_MSG)
    if project.archived:
        raise HTTPException(status_code=422, detail=_GATE_LEGACY_MSG)

    # Authority: Lead (rank 3) OR global Admin only
    global_role = user.role
    project_rank = _resolve_project_rank(user, project_id)
    if not (global_role == "Admin" or project_rank >= _LEAD_RANK):
        raise HTTPException(status_code=403, detail=_GATE_AUTHORITY_MSG)

    # Byte-exact project name match — NO .strip(), NO .lower() (C-3 requirement)
    if body.scope_acknowledgement_text != project.name:
        raise HTTPException(status_code=422, detail=_GATE_NAME_MISMATCH_MSG)
    # body.confirm_authorisation is Literal[True] — Pydantic enforces at deserialization.

    now = datetime.now(timezone.utc)
    user_sub = user.id
    await db.execute(
        sql_update(Project)
        .where(Project.id == project_id)
        .values(
            active_scans_authorised=True,
            scope_acknowledgement_text=body.scope_acknowledgement_text,
            active_auth_confirmed_at=now,
            active_auth_confirmed_by=user_sub,
        )
    )
    await db.commit()

    log.info(
        "easm_gate_flipped",
        user_sub=user_sub,
        project_id=str(project_id),
        action="flip",
        timestamp=now.isoformat(),
    )

    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one()
    return await _hydrate(db, project, current_user_sub=user_sub)


@router.delete("/{project_id}/easm-gate", response_model=ProjectResponse)
async def revoke_easm_gate(
    project_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> ProjectResponse:
    """Revoke active-scan gate. Clears all four gate fields.

    Canonical copy (UI-SPEC §Error states):
    - 403: "You do not have permission to authorise active scans. Lead or Admin role required."
    """
    user: AuthUser = request.state.user
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="project_not_found")

    # Authority: Lead OR global Admin only
    global_role = user.role
    project_rank = _resolve_project_rank(user, project_id)
    if not (global_role == "Admin" or project_rank >= _LEAD_RANK):
        raise HTTPException(status_code=403, detail=_GATE_AUTHORITY_MSG)

    user_sub = user.id
    now = datetime.now(timezone.utc)
    await db.execute(
        sql_update(Project)
        .where(Project.id == project_id)
        .values(
            active_scans_authorised=False,
            scope_acknowledgement_text=None,
            active_auth_confirmed_at=None,
            active_auth_confirmed_by=None,
        )
    )
    await db.commit()

    log.info(
        "easm_gate_revoked",
        user_sub=user_sub,
        project_id=str(project_id),
        action="revoke",
        timestamp=now.isoformat(),
    )

    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one()
    return await _hydrate(db, project, current_user_sub=user_sub)


# ---------------------------------------------------------------------------
# DELETE /{id} — disabled (405)
# ---------------------------------------------------------------------------


@router.delete("/{project_id}", status_code=405)
async def hard_delete_disabled(project_id: uuid.UUID) -> Response:
    """Hard delete is disabled — the only deletion path is POST /archive."""
    raise HTTPException(
        status_code=405,
        detail="hard_delete_disabled — use POST /api/projects/{id}/archive",
    )


# ---------------------------------------------------------------------------
# Membership endpoints — nested under /{project_id}/memberships
# ---------------------------------------------------------------------------


def _count_leads_excluding_stmt(
    project_id: uuid.UUID,
    exclude_membership_id: uuid.UUID | None,
):
    """Build a SELECT COUNT(*) statement for Lead memberships, optionally excluding one."""
    stmt = (
        select(func.count(ProjectMembership.id))
        .where(ProjectMembership.project_id == project_id)
        .where(ProjectMembership.project_role == ProjectRole.Lead.value)
    )
    if exclude_membership_id is not None:
        stmt = stmt.where(ProjectMembership.id != exclude_membership_id)
    return stmt


async def _assert_not_last_lead(
    db: AsyncSession,
    project_id: uuid.UUID,
    membership: ProjectMembership,
) -> None:
    """Raise 409 if removing/demoting `membership` would leave the project Lead-less.

    No-op when the membership being changed is NOT currently a Lead (demoting a
    Contributor/Observer cannot reduce the Lead count).
    """
    if membership.project_role != ProjectRole.Lead.value:
        return
    remaining = (
        await db.execute(_count_leads_excluding_stmt(project_id, membership.id))
    ).scalar_one()
    if remaining == 0:
        raise HTTPException(status_code=409, detail="cannot_remove_last_lead")


@router.get(
    "/{project_id}/memberships", response_model=list[MembershipResponse]
)
async def list_memberships(
    project_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    db: AsyncSession = Depends(get_session),
) -> list[MembershipResponse]:
    p_name = (
        await db.execute(select(Project.name).where(Project.id == project_id))
    ).scalar_one_or_none()
    if p_name is None:
        raise HTTPException(status_code=404, detail="project_not_found")
    rows = (
        await db.execute(
            select(ProjectMembership)
            .where(ProjectMembership.project_id == project_id)
            .order_by(ProjectMembership.created_at.asc())
        )
    ).scalars().all()
    return [
        MembershipResponse(
            id=m.id,
            project_id=m.project_id,
            user_sub=m.user_sub,
            project_role=m.project_role,  # type: ignore[arg-type]
            added_by=m.added_by,
            created_at=m.created_at,
            project_name=p_name,
        )
        for m in rows
    ]


@router.post(
    "/{project_id}/memberships",
    response_model=MembershipResponse,
    status_code=201,
)
async def add_member(
    project_id: uuid.UUID,
    body: MembershipCreate,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> MembershipResponse:
    _legacy_guard(project_id)
    m = ProjectMembership(
        user_sub=body.user_sub,
        project_id=project_id,
        project_role=body.project_role,
        added_by=user.id,
    )
    db.add(m)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="membership_exists")
    await db.refresh(m)
    p_name = (
        await db.execute(select(Project.name).where(Project.id == project_id))
    ).scalar_one()
    log.info(
        "membership_added",
        project_id=str(project_id),
        user_sub=body.user_sub,
        role=body.project_role,
        added_by=user.id,
    )
    return MembershipResponse(
        id=m.id,
        project_id=m.project_id,
        user_sub=m.user_sub,
        project_role=m.project_role,  # type: ignore[arg-type]
        added_by=m.added_by,
        created_at=m.created_at,
        project_name=p_name,
    )


@router.patch(
    "/{project_id}/memberships/{membership_id}",
    response_model=MembershipResponse,
)
async def update_member_role(
    project_id: uuid.UUID,
    membership_id: uuid.UUID,
    body: MembershipUpdate,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> MembershipResponse:
    _legacy_guard(project_id)
    m = (
        await db.execute(
            select(ProjectMembership).where(
                and_(
                    ProjectMembership.id == membership_id,
                    ProjectMembership.project_id == project_id,
                )
            )
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="membership_not_found")
    # Demoting a Lead to non-Lead? Guard against last-Lead removal.
    if (
        m.project_role == ProjectRole.Lead.value
        and body.project_role != ProjectRole.Lead.value
    ):
        await _assert_not_last_lead(db, project_id, m)
    m.project_role = body.project_role
    await db.commit()
    await db.refresh(m)
    p_name = (
        await db.execute(select(Project.name).where(Project.id == project_id))
    ).scalar_one()
    log.info(
        "membership_role_updated",
        membership_id=str(membership_id),
        new_role=body.project_role,
        updated_by=user.id,
    )
    return MembershipResponse(
        id=m.id,
        project_id=m.project_id,
        user_sub=m.user_sub,
        project_role=m.project_role,  # type: ignore[arg-type]
        added_by=m.added_by,
        created_at=m.created_at,
        project_name=p_name,
    )


@router.delete(
    "/{project_id}/memberships/{membership_id}", status_code=204
)
async def remove_member(
    project_id: uuid.UUID,
    membership_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> Response:
    _legacy_guard(project_id)
    m = (
        await db.execute(
            select(ProjectMembership).where(
                and_(
                    ProjectMembership.id == membership_id,
                    ProjectMembership.project_id == project_id,
                )
            )
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="membership_not_found")
    await _assert_not_last_lead(db, project_id, m)
    await db.delete(m)
    await db.commit()
    log.info(
        "membership_removed",
        membership_id=str(membership_id),
        removed_by=user.id,
    )
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Scope rows (PRJ-02) — 7-type row CRUD with per-type value validators
# ---------------------------------------------------------------------------


@router.get("/{project_id}/scope", response_model=list[ScopeRowResponse])
async def list_scope_rows(
    project_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    db: AsyncSession = Depends(get_session),
) -> list[ScopeRowResponse]:
    """Return all scope rows for a project, ordered by scope_type then value."""
    rows = (
        await db.execute(
            select(ProjectScopeRow)
            .where(ProjectScopeRow.project_id == project_id)
            .order_by(ProjectScopeRow.scope_type.asc(), ProjectScopeRow.value.asc())
        )
    ).scalars().all()
    return [ScopeRowResponse.model_validate(r) for r in rows]


@router.post(
    "/{project_id}/scope", response_model=ScopeRowResponse, status_code=201
)
async def add_scope_row(
    project_id: uuid.UUID,
    body: ScopeRowCreate,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Contributor)),
    db: AsyncSession = Depends(get_session),
) -> ScopeRowResponse:
    """Validate the row value per scope_type, then INSERT. 422 on invalid value;
    409 on UniqueConstraint violation (duplicate row)."""
    _legacy_guard(project_id)
    try:
        canonical = validate_scope_row_value(body.scope_type, body.value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    row = ProjectScopeRow(
        id=uuid.uuid4(),
        project_id=project_id,
        scope_type=body.scope_type,
        value=canonical,
        contact=body.contact,
        exclude=body.exclude,
        active_test_scope=body.active_test_scope,
        intel_scope=body.intel_scope,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="duplicate_scope_row")
    await db.refresh(row)
    log.info(
        "scope_row_added",
        project_id=str(project_id),
        scope_type=body.scope_type,
        value=canonical,
    )
    return ScopeRowResponse.model_validate(row)


@router.patch(
    "/{project_id}/scope/{row_id}", response_model=ScopeRowResponse
)
async def update_scope_row(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    body: ScopeRowUpdate,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Contributor)),
    db: AsyncSession = Depends(get_session),
) -> ScopeRowResponse:
    """Partial-update of a scope row. The Pydantic model_validator on
    ScopeRowUpdate rejects both-flags-false bodies at the 422 layer; the DB
    CHECK constraint project_scope_rows_at_least_one_flag enforces the same
    invariant in depth."""
    _legacy_guard(project_id)
    row = (
        await db.execute(
            select(ProjectScopeRow).where(
                and_(
                    ProjectScopeRow.id == row_id,
                    ProjectScopeRow.project_id == project_id,
                )
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="scope_row_not_found")
    if body.contact is not None:
        row.contact = body.contact
    if body.exclude is not None:
        row.exclude = body.exclude
    if body.active_test_scope is not None:
        row.active_test_scope = body.active_test_scope
    if body.intel_scope is not None:
        row.intel_scope = body.intel_scope
    # Enforce the CHECK constraint invariant at the 422 layer against the
    # merged (current + patch) state — ScopeRowUpdate's model_validator only
    # sees the patch body, not the current row, so a patch of {intel_scope:
    # false} passes Pydantic even when the row already has active_test_scope
    # false. Without this guard the commit raises IntegrityError → 500.
    if not (row.active_test_scope or row.intel_scope):
        raise HTTPException(
            status_code=422,
            detail="Row must target at least intel or active test.",
        )
    await db.commit()
    await db.refresh(row)
    return ScopeRowResponse.model_validate(row)


@router.delete("/{project_id}/scope/{row_id}", status_code=204)
async def delete_scope_row(
    project_id: uuid.UUID,
    row_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Contributor)),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a single scope row. 404 if the row does not belong to the project."""
    _legacy_guard(project_id)
    row = (
        await db.execute(
            select(ProjectScopeRow).where(
                and_(
                    ProjectScopeRow.id == row_id,
                    ProjectScopeRow.project_id == project_id,
                )
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="scope_row_not_found")
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# project_sources binding (PRJ-05) — atomic-replace multi-select
# ---------------------------------------------------------------------------
#
# Semantics per CONTEXT.md §project_sources binding:
#   - PUT accepts the FULL desired source_ids list; delete-then-insert in a
#     single transaction (atomic replace — not append).
#   - Empty list removes all bindings — events_query then falls back to the
#     default "all sources visible" path for the project.
#   - FK on source_id -> sources.id rejects unknown ids with IntegrityError
#     which we translate to 422 `unknown_source_id`.
#   - GET returns bound source_ids hydrated with Source.name + feed_type so the
#     UI can render a labelled multiselect without a second API round trip.


class ProjectSourceResponse(BaseModel):
    """Hydrated response row for GET /api/projects/{id}/sources."""

    source_id: uuid.UUID
    source_name: str
    feed_type: str
    created_at: datetime


@router.get(
    "/{project_id}/sources", response_model=list[ProjectSourceResponse]
)
async def list_project_sources(
    project_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    db: AsyncSession = Depends(get_session),
) -> list[ProjectSourceResponse]:
    """Return bound project_sources rows joined to Source for display metadata."""
    rows = (
        await db.execute(
            select(
                ProjectSource.source_id,
                Source.name,
                Source.feed_type,
                ProjectSource.created_at,
            )
            .join(Source, Source.id == ProjectSource.source_id)
            .where(ProjectSource.project_id == project_id)
            .order_by(Source.name.asc())
        )
    ).all()
    return [
        ProjectSourceResponse(
            source_id=r.source_id,
            source_name=r.name,
            feed_type=r.feed_type,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.put(
    "/{project_id}/sources", response_model=list[ProjectSourceResponse]
)
async def replace_project_sources(
    project_id: uuid.UUID,
    body: ProjectSourcesBinding,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Contributor)),
    db: AsyncSession = Depends(get_session),
) -> list[ProjectSourceResponse]:
    """Atomically replace the project_sources binding set.

    DELETE existing rows + INSERT new rows in a single transaction. FK
    violation (unknown source_id) triggers rollback + 422 with detail
    ``unknown_source_id``.
    """
    _legacy_guard(project_id)
    await db.execute(
        sql_delete(ProjectSource).where(ProjectSource.project_id == project_id)
    )
    for sid in body.source_ids:
        db.add(ProjectSource(project_id=project_id, source_id=sid))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=422, detail="unknown_source_id")
    rows = (
        await db.execute(
            select(
                ProjectSource.source_id,
                Source.name,
                Source.feed_type,
                ProjectSource.created_at,
            )
            .join(Source, Source.id == ProjectSource.source_id)
            .where(ProjectSource.project_id == project_id)
            .order_by(Source.name.asc())
        )
    ).all()
    log.info(
        "project_sources_replaced",
        project_id=str(project_id),
        bound_count=len(body.source_ids),
    )
    return [
        ProjectSourceResponse(
            source_id=r.source_id,
            source_name=r.name,
            feed_type=r.feed_type,
            created_at=r.created_at,
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# PRJ-07 Export endpoint — POST /{project_id}/export
# ---------------------------------------------------------------------------


@router.post("/{project_id}/export")
async def export_project(
    project_id: uuid.UUID,
    format: Literal["stix", "csv"] = Query(...),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Contributor)),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """PRJ-07 per-project export — STIX 2.1 Bundle OR CSV.

    Auth: Contributor+ on project (or global Admin bypass via require_project_membership).
    Observer is rejected by the Contributor minimum. 50k event cap -> 413.
    Caps read via module-ref (_project_export.STIX_BUNDLE_EVENT_CAP) so tests can monkeypatch.
    """
    _legacy_guard(project_id)

    # Load project for filename + STIX metadata
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="project_not_found")

    # Cap check — module-ref so monkeypatch in tests is observable to the handler
    count = await _project_export.count_exportable_events(db, project_id)
    cap = (
        _project_export.STIX_BUNDLE_EVENT_CAP
        if format == "stix"
        else _project_export.CSV_EVENT_CAP
    )
    if count > cap:
        raise HTTPException(
            status_code=413,
            detail=f"export exceeds {cap}-event cap ({count} events) — narrow the project scope or filter",
        )

    events = await _project_export.fetch_scoped_events(db, project_id)
    filename = _project_export.export_filename(project.name, format)

    if format == "stix":
        scope_rows = await fetch_scope_rows_intel(db, project_id)
        body = _project_export.build_stix_bundle(project, events, scope_rows)
        media_type = "application/json"
        body_bytes = body.encode("utf-8")
    else:  # csv
        body_bytes = await _project_export.build_csv_bytes(db, events)
        media_type = "text/csv"

    return StreamingResponse(
        iter([body_bytes]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Scoring routes — SCR-02 / SCR-03
# GET  /{project_id}/scoring            → Observer+  (read effective rules)
# PUT  /{project_id}/scoring            → Lead+      (save rules + trigger rescore)
# POST /{project_id}/rescore            → Lead+      (manual rescore trigger)
# GET  /{project_id}/rescore/status     → Observer+  (rescore status)
# ---------------------------------------------------------------------------


@router.get("/{project_id}/scoring", response_model=ScoringRulesRead)
async def get_scoring_rules(
    project_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    db: AsyncSession = Depends(get_session),
) -> ScoringRulesRead:
    """Return the effective scoring rules for a project.

    If no override row exists, returns DEFAULT_SCORING_CONFIG with
    version=1 and is_default=True. If an override row exists, returns
    the stored rules with is_default=False.
    """
    from app.services.scoring.defaults import DEFAULT_SCORING_CONFIG  # noqa: PLC0415

    row = (
        await db.execute(
            select(ProjectScoringRules).where(
                ProjectScoringRules.project_id == project_id
            )
        )
    ).scalar_one_or_none()

    if row is None:
        return ScoringRulesRead(
            project_id=project_id,
            version=1,
            rules=DEFAULT_SCORING_CONFIG,
            is_default=True,
        )

    return ScoringRulesRead(
        project_id=project_id,
        version=row.version,
        rules=row.rules,
        is_default=False,
    )


@router.put("/{project_id}/scoring", response_model=ScoringRulesRead)
async def put_scoring_rules(
    project_id: uuid.UUID,
    body: ScoringRulesPayload,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    db: AsyncSession = Depends(get_session),
) -> ScoringRulesRead:
    """Persist per-project scoring rules, bump version, and enqueue rescore actor.

    Pydantic validates weights sum=100 and tier cutoffs descending before this
    handler is invoked — malformed payloads return 422 automatically.

    Upsert semantics: if a row exists, increment version + update rules + updated_at;
    otherwise INSERT a new row at version=1.
    After commit, enqueues rescore_project Dramatiq actor on the scoring queue.
    """
    from app.workers.scoring import rescore_project  # noqa: PLC0415

    rules_dict = body.model_dump()

    row = (
        await db.execute(
            select(ProjectScoringRules).where(
                ProjectScoringRules.project_id == project_id
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if row is None:
        row = ProjectScoringRules(
            id=uuid.uuid4(),
            project_id=project_id,
            version=1,
            rules=rules_dict,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.version = row.version + 1
        row.rules = rules_dict
        row.updated_at = now

    await db.commit()
    await db.refresh(row)

    rescore_project.send(str(project_id))

    log.info(
        "scoring_rules_updated",
        project_id=str(project_id),
        version=row.version,
    )

    return ScoringRulesRead(
        project_id=project_id,
        version=row.version,
        rules=row.rules,
        is_default=False,
    )


@router.post("/{project_id}/rescore", status_code=202)
async def trigger_rescore(
    project_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
) -> dict:
    """Manually enqueue the rescore_project Dramatiq actor for this project.

    Returns 202 with {"queued": true, "project_id": "<uuid>"} to indicate
    the task has been accepted. The actor runs asynchronously on the scoring queue.
    """
    from app.workers.scoring import rescore_project  # noqa: PLC0415

    rescore_project.send(str(project_id))
    log.info("rescore_manually_triggered", project_id=str(project_id))
    return {"queued": True, "project_id": str(project_id)}


@router.get("/{project_id}/rescore/status", response_model=RescoreStatusResponse)
async def get_rescore_status(
    project_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    db: AsyncSession = Depends(get_session),
) -> RescoreStatusResponse:
    """Return rescore status for a project.

    last_rescore_at: most recent scored_at from event_score_overrides for this project.
    total_count: number of event_score_override rows for this project.
    in_progress_count: 1 when rescore_project actor is currently executing for this
        project (Redis key rescore:project:{id}:active exists), else 0. Redis failure
        degrades to 0 — polling never blocks on Redis.
    """
    result = (
        await db.execute(
            select(
                func.max(EventScoreOverride.scored_at),
                func.count(EventScoreOverride.event_id),
            ).where(EventScoreOverride.project_id == project_id)
        )
    ).one()

    last_rescore_at, total_count = result

    # SCR-02 advisory gap closure (plan 15-11): query Redis for active rescore flag.
    # Key written by app.workers.scoring._async_rescore on entry, deleted in finally.
    # TTL safety net (1800s) protects against crashed actor leaving stale 1.
    in_progress_count = 0
    try:
        from app.services.redis_client import get_redis  # noqa: PLC0415
        redis = await get_redis()
        exists = await redis.exists(f"rescore:project:{project_id}:active")
        in_progress_count = 1 if exists else 0
    except Exception as exc:  # noqa: BLE001 — never 5xx the status poll on Redis hiccup
        log.warning(
            "rescore_inprogress_flag_read_failed project_id=%s error=%r",
            project_id,
            exc,
        )
        in_progress_count = 0

    return RescoreStatusResponse(
        last_rescore_at=last_rescore_at,
        in_progress_count=in_progress_count,
        total_count=total_count or 0,
    )


# ---------------------------------------------------------------------------
# AI provider routes — AI-04, AI-05, SCR-04
# GET  /{project_id}/ai-provider          → Observer+ (read config, no key)
# PUT  /{project_id}/ai-provider          → Admin only (upsert config + encrypt key)
# POST /{project_id}/ai-provider/test     → Admin only (ping LLM provider)
# POST /{project_id}/ai-rescore           → Admin only (enqueue AI rescore)
# GET  /{project_id}/ai/rerank/status     → Observer+ (rerank progress)
# ---------------------------------------------------------------------------


@router.get("/{project_id}/ai-provider", response_model=AIProviderRead)
async def get_ai_provider(
    project_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    db: AsyncSession = Depends(get_session),
) -> AIProviderRead:
    """Return AI provider config for a project. Credentials are never returned in plaintext."""
    from app.models.ai import AIProvider  # noqa: PLC0415

    row = (
        await db.execute(select(AIProvider).where(AIProvider.project_id == project_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="ai_provider_not_configured")

    # Load project for ai_* flags
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="project_not_found")

    return AIProviderRead(
        id=row.id,
        project_id=row.project_id,
        provider_type=row.provider_type,  # type: ignore[arg-type]
        model_name=row.model_name,
        api_base=row.api_base,
        api_key_masked="••••••••" if row.credentials_enc else None,
        credentials_key_version=row.credentials_key_version,
        ai_rerank_enabled=project.ai_rerank_enabled,
        ai_digest_enabled=project.ai_digest_enabled,
        ai_auto_summary_enabled=project.ai_auto_summary_enabled,
        ai_daily_token_cap=project.ai_daily_token_cap,
        digest_schedule_cron=project.digest_schedule_cron,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.put("/{project_id}/ai-provider", response_model=AIProviderRead)
async def upsert_ai_provider(
    project_id: uuid.UUID,
    body: AIProviderUpdate,
    _admin: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> AIProviderRead:
    """Upsert AI provider config. Admin only. api_key is encrypted at write time."""
    from app.config import settings as _cfg  # noqa: PLC0415
    from app.crypto import encrypt_credentials  # noqa: PLC0415
    from app.models.ai import AIProvider  # noqa: PLC0415
    from app.workers.ai import ai_rescore_project  # noqa: PLC0415

    # NOTE: _legacy_guard is intentionally NOT called here. The AIProvider row
    # keyed to LEGACY_PROJECT_ID doubles as the system-wide AI default
    # (editable via /admin/ai-defaults). All other LEGACY mutations (rename,
    # scope, members, etc.) remain blocked at their respective endpoints.
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="project_not_found")

    row = (
        await db.execute(select(AIProvider).where(AIProvider.project_id == project_id))
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if row is None:
        row = AIProvider(
            id=uuid.uuid4(),
            project_id=project_id,
            provider_type=body.provider_type or "ollama",
            model_name=body.model_name or "llama3",
            api_base=body.api_base,
            credentials_enc=(
                encrypt_credentials(_cfg.SECRET_KEY, {"api_key": body.api_key})
                if body.api_key
                else None
            ),
        )
        db.add(row)
    else:
        if body.provider_type is not None:
            row.provider_type = body.provider_type
        if body.model_name is not None:
            row.model_name = body.model_name
        if body.api_base is not None:
            row.api_base = body.api_base
        if body.api_key is not None:
            row.credentials_enc = encrypt_credentials(
                _cfg.SECRET_KEY, {"api_key": body.api_key}
            )
        row.updated_at = now

    # Track whether ai_rerank_enabled is transitioning false→true
    prev_rerank = project.ai_rerank_enabled

    # Update project-level AI flags
    if body.ai_rerank_enabled is not None:
        project.ai_rerank_enabled = body.ai_rerank_enabled
    if body.ai_digest_enabled is not None:
        project.ai_digest_enabled = body.ai_digest_enabled
    if body.ai_auto_summary_enabled is not None:
        project.ai_auto_summary_enabled = body.ai_auto_summary_enabled
    if body.ai_daily_token_cap is not None:
        project.ai_daily_token_cap = body.ai_daily_token_cap
    if body.digest_schedule_cron is not None:
        project.digest_schedule_cron = body.digest_schedule_cron

    await db.commit()
    await db.refresh(row)
    await db.refresh(project)

    # Enqueue one-shot rerank on false→true transition
    if not prev_rerank and project.ai_rerank_enabled:
        try:
            ai_rescore_project.send(str(project_id))
            log.info("ai_rescore_enqueued_on_rerank_enable", project_id=str(project_id))
        except Exception as exc:  # noqa: BLE001
            log.warning("ai_rescore_enqueue_failed project_id=%s error=%s", project_id, exc)

    return AIProviderRead(
        id=row.id,
        project_id=row.project_id,
        provider_type=row.provider_type,  # type: ignore[arg-type]
        model_name=row.model_name,
        api_base=row.api_base,
        api_key_masked="••••••••" if row.credentials_enc else None,
        credentials_key_version=row.credentials_key_version,
        ai_rerank_enabled=project.ai_rerank_enabled,
        ai_digest_enabled=project.ai_digest_enabled,
        ai_auto_summary_enabled=project.ai_auto_summary_enabled,
        ai_daily_token_cap=project.ai_daily_token_cap,
        digest_schedule_cron=project.digest_schedule_cron,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/{project_id}/ai-provider/test", response_model=AIProviderTestResponse)
async def test_ai_provider(
    project_id: uuid.UUID,
    _admin: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> AIProviderTestResponse:
    """Ping the configured LLM provider with a minimal completion to verify connectivity."""
    import time  # noqa: PLC0415

    import litellm  # noqa: PLC0415

    from app.services.llm.client import resolve_provider  # noqa: PLC0415

    try:
        model_str, api_base, api_key = await resolve_provider(db, project_id)
    except ValueError as exc:
        return AIProviderTestResponse(ok=False, latency_ms=0, error=str(exc))

    kwargs: dict = {
        "model": model_str,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5,
        "timeout": 10,
    }
    if api_base is not None:
        kwargs["api_base"] = api_base
    if api_key is not None:
        kwargs["api_key"] = api_key

    t0 = time.monotonic()
    try:
        await litellm.acompletion(**kwargs)
        latency_ms = int((time.monotonic() - t0) * 1000)
        return AIProviderTestResponse(ok=True, latency_ms=latency_ms)
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.monotonic() - t0) * 1000)
        return AIProviderTestResponse(ok=False, latency_ms=latency_ms, error=str(exc))


@router.get("/{project_id}/ai-provider/ollama-models")
async def list_ollama_models(
    project_id: uuid.UUID,
    _admin: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """List installed Ollama models so the UI can offer a dropdown.

    Resolves the api_base via the same precedence as resolve_provider (project
    api_base → OLLAMA_BASE_URL env → http://ollama:11434), so the dropdown
    reflects what the worker will actually reach. project_id is in the path
    only for auth scoping; the call hits the cluster-wide ollama instance.
    """
    import os  # noqa: PLC0415
    import httpx  # noqa: PLC0415
    from app.models.ai import AIProvider  # noqa: PLC0415

    row = (
        await db.execute(select(AIProvider).where(AIProvider.project_id == project_id))
    ).scalar_one_or_none()
    env_default = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
    api_base = (row.api_base if row else None) or env_default
    if "localhost" in api_base or "127.0.0.1" in api_base:
        api_base = env_default

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{api_base.rstrip('/')}/api/tags")
            r.raise_for_status()
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "models": [], "error": str(exc)}

    models = [m.get("name") for m in (data.get("models") or []) if m.get("name")]
    return {"ok": True, "models": models}


@router.post("/{project_id}/ai-rescore", status_code=202)
async def trigger_ai_rescore(
    project_id: uuid.UUID,
    _admin: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Manually enqueue the ai_rescore_project actor. Admin only.

    Checks ai_rerank_enabled on the project — returns 409 if disabled.
    """
    from app.workers.ai import ai_rescore_project  # noqa: PLC0415

    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="project_not_found")
    if not project.ai_rerank_enabled:
        raise HTTPException(status_code=409, detail="ai_rerank_not_enabled")

    ai_rescore_project.send(str(project_id))
    log.info("ai_rescore_manually_triggered", project_id=str(project_id))
    return {"queued": True}


@router.get("/{project_id}/ai/rerank/status", response_model=AIRerankStatus)
async def get_ai_rerank_status(
    project_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    db: AsyncSession = Depends(get_session),
) -> AIRerankStatus:
    """Return AI rerank status for a project.

    last_rerank_at: most recent ai_score non-null event in last 24h.
    in_progress: true when ai:rerank:project:{id}:active Redis key exists.
    total_count: count of events with non-null ai_score in last 24h.
    """
    from datetime import timedelta  # noqa: PLC0415

    from sqlalchemy import text as sa_text  # noqa: PLC0415

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    result = (
        await db.execute(
            sa_text(
                "SELECT MAX(observed_at), COUNT(*) FROM events "
                "WHERE project_id = :pid AND ai_score IS NOT NULL AND observed_at >= :cutoff"
            ).bindparams(pid=project_id, cutoff=cutoff)
        )
    ).one()
    last_rerank_at, total_count = result

    in_progress = False
    try:
        from app.services.redis_client import get_redis  # noqa: PLC0415

        redis = await get_redis()
        exists = await redis.exists(f"ai:rerank:project:{project_id}:active")
        in_progress = bool(exists)
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        log.warning(
            "ai_rerank_inprogress_flag_read_failed project_id=%s error=%r",
            project_id,
            exc,
        )

    return AIRerankStatus(
        last_rerank_at=last_rerank_at,
        in_progress_count=1 if in_progress else 0,
        total_count=int(total_count or 0),
    )


# ---------------------------------------------------------------------------
# Attack path analysis — ATK-01..ATK-05
# ---------------------------------------------------------------------------

from app.services.llm.attack_path import analyse_attack_path  # noqa: E402
from litellm.exceptions import APIConnectionError as LiteLLMConnectionError, Timeout as LiteLLMTimeout  # noqa: E402


@router.post("/{project_id}/attack-path", response_model=AttackPathResponse)
async def analyse_project_attack_path(
    project_id: uuid.UUID,
    body: AttackPathRequest,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> AttackPathResponse:
    """Reconstruct MITRE ATT&CK kill-chain from project events via LLM.

    Auth: Observer+ project membership required.
    Body: { "days": 30 }  (default 30, max 90)
    Returns: Structured attack path graph (nodes + edges).
    """
    _legacy_guard(project_id)
    try:
        return await analyse_attack_path(db, project_id, body.days, user)
    except (LiteLLMConnectionError, LiteLLMTimeout) as exc:
        raise HTTPException(
            status_code=504,
            detail="AI provider timed out — local models (Ollama) may be too slow for this request. Configure an OpenAI or Anthropic provider in Admin → AI Settings for faster results.",
        ) from exc
    except ValueError as exc:
        msg = str(exc)
        if "No events" in msg:
            raise HTTPException(status_code=400, detail="No events in window") from exc
        if "No AI provider" in msg or "provider" in msg.lower():
            raise HTTPException(status_code=503, detail="AI provider not configured") from exc
        raise HTTPException(status_code=500, detail=msg) from exc


# ---------------------------------------------------------------------------
# PRJ-06 compare_router — sibling APIRouter at /projects/compare
# Registered BEFORE projects_router in main.py so /api/projects/compare
# does not collide with /{project_id} route on the main router.
# ---------------------------------------------------------------------------

compare_router = APIRouter(prefix="/projects/compare", tags=["projects"])


@compare_router.get("", response_model=CompareResponse)
async def compare_projects(
    a: uuid.UUID = Query(...),
    b: uuid.UUID = Query(...),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> CompareResponse:
    """PRJ-06 cross-project compare — shared actors / techniques / IOCs.

    Auth: Observer+ on BOTH projects (or global Admin bypass).
    Empty arrays on no-overlap (not 404). 500-row cap per panel (service-side).
    """
    await check_project_membership(user, db, a, ProjectRole.Observer)
    await check_project_membership(user, db, b, ProjectRole.Observer)

    actors = await shared_actors(db, a, b)
    techniques = await shared_techniques(db, a, b)
    iocs_raw = await shared_iocs(db, a, b)
    return CompareResponse(
        shared_actors=actors,
        shared_techniques=techniques,
        shared_iocs=[SharedIOCSchema(kind=i["kind"], value=i["value"]) for i in iocs_raw],
    )
