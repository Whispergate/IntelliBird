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

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import and_, delete as sql_delete, func, select, update as sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_analyst_or_above, require_auth
from app.models.projects import (
    LEGACY_PROJECT_ID,
    Project,
    ProjectMembership,
    ProjectRole,
    ProjectScopeRow,
    ProjectSource,
)
from app.models.sources import Source
from app.schemas.projects import (
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
)
from app.schemas.easm import EASMGateFlipRequest
from app.security.jwt import AuthUser, PROJECT_ROLE_RANK
from app.security.project_membership import require_project_membership
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
    # §Established Patterns carry-over from Phase 3 source registry pattern).
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
