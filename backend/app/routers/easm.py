"""EASM routes (Phase 11).

Mounted paths (registered in main.py):
  safelist_router prefix="/api":
    GET    /api/easm/safelist                                    (any authenticated user)

  router prefix="/api":
    POST   /api/projects/{project_id}/easm/scans                (launch scan)
    GET    /api/projects/{project_id}/easm/scans                (list scans)
    GET    /api/projects/{project_id}/easm/scans/{scan_id}      (single scan)
    DELETE /api/projects/{project_id}/easm/scans/{scan_id}      (cancel scan)
    GET    /api/projects/{project_id}/easm/scans/{scan_id}/diff (EASM-08 diff)
    GET    /api/projects/{project_id}/easm/findings             (list findings)
    PATCH  /api/projects/{project_id}/easm/findings/{finding_id} (lifecycle patch)
    GET    /api/projects/{project_id}/easm/scans/{scan_id}/findings (scan-scoped findings)

Active-scan gate enforcement is defence-in-depth — plan 11-06 (projects router
PATCH /{id}/easm-gate) is the canonical gate-flip endpoint. The gate check here
re-reads the project row BEFORE queue dispatch so a tampered request body cannot
reach the BBOT subprocess without all three fields set and within TTL.

Authority matrix (CONTEXT.md §Scan authority matrix):
  Launch passive: Admin, Analyst (global), Lead, Contributor (project)
  Launch active:  Admin (global), Lead (project) only
  Cancel scan:    Admin (global), Lead (project), Contributor who launched it
  Lifecycle PATCH: Admin, Analyst (global), Lead, Contributor (project) — Observer blocked
  All GETs:       any project member (Observer+) or global Admin
"""
from __future__ import annotations

import datetime
import uuid

import redis as redis_lib
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.middleware.auth import require_auth
from app.models.easm import EASMFinding, EASMScan
from app.models.projects import LEGACY_PROJECT_ID, Project
from app.schemas.easm import (
    EASMDiffChangedEntry,
    EASMDiffEntry,
    EASMDiffResponse,
    EASMFindingLifecyclePatch,
    EASMFindingResponse,
    EASMSafelistResponse,
    EASMScanCreate,
    EASMScanResponse,
)
from app.security.jwt import AuthUser, PROJECT_ROLE_RANK
from app.services import bbot_runner, bbot_safelist
from app.workers.easm import run_bbot_scan

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Two routers:
#   router           → mounted at /api (handles /api/projects/... paths)
#   safelist_router  → mounted at /api (handles /api/easm/safelist — no project scope)
# ---------------------------------------------------------------------------
router = APIRouter(tags=["easm"])
safelist_router = APIRouter(tags=["easm"])

_LEAD_RANK = PROJECT_ROLE_RANK["Lead"]
_CONTRIBUTOR_RANK = PROJECT_ROLE_RANK["Contributor"]
_OBSERVER_RANK = PROJECT_ROLE_RANK["Observer"]


# ---------------------------------------------------------------------------
# GET /api/easm/safelist — public to any authenticated user (no project scope)
# ---------------------------------------------------------------------------

@safelist_router.get("/easm/safelist", response_model=EASMSafelistResponse)
async def get_safelist(
    _user: AuthUser = Depends(require_auth),
) -> EASMSafelistResponse:
    """Return the effective module safelist + BBOT version + credential requirements.

    UI populates its module multi-select from this endpoint — single source of truth.
    """
    modules = sorted(bbot_safelist.get_effective_safelist())
    return EASMSafelistResponse(
        modules=modules,
        bbot_version=bbot_safelist.BBOT_VERSION,
        requires_credentials=dict(bbot_safelist.MODULE_CREDENTIAL_REQUIREMENTS),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_project_rank(user: AuthUser, project_id: uuid.UUID) -> int:
    """Return the caller's numeric project rank (1=Observer, 2=Contributor, 3=Lead).

    Returns 0 when the user has no membership for the project.
    Global Admin callers should be short-circuited before reaching this helper.
    """
    pid_str = str(project_id)
    return user.project_memberships.get(pid_str, 0)


def _require_project_member(user: AuthUser, project_id: uuid.UUID) -> None:
    """Raise 403 unless the user is a global Admin or holds any project membership."""
    if user.role == "Admin":
        return
    if _resolve_project_rank(user, project_id) >= _OBSERVER_RANK:
        return
    raise HTTPException(status_code=403, detail="not_project_member")


async def _load_project_or_404(db: AsyncSession, project_id: uuid.UUID) -> Project:
    """Load a Project row; 404 on missing, 422 on archived/legacy."""
    p = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="project_not_found")
    if p.id == LEGACY_PROJECT_ID or p.archived:
        raise HTTPException(
            status_code=422,
            detail="Scans cannot be launched against archived or legacy projects.",
        )
    return p


def _is_active_gate_valid(p: Project) -> bool:
    """Return True iff the three-factor active-scan gate is set and within TTL (C-3)."""
    if not getattr(p, "active_scans_authorised", False):
        return False
    if not getattr(p, "scope_acknowledgement_text", None):
        return False
    confirmed_at = getattr(p, "active_auth_confirmed_at", None)
    if confirmed_at is None:
        return False
    ttl = datetime.timedelta(seconds=settings.BBOT_ACTIVE_AUTH_TTL_SECONDS)
    now = datetime.datetime.now(datetime.timezone.utc)
    if confirmed_at.tzinfo is None:
        confirmed_at = confirmed_at.replace(tzinfo=datetime.timezone.utc)
    return (now - confirmed_at) < ttl


async def _findings_count_for(db: AsyncSession, scan_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(EASMFinding).where(EASMFinding.scan_id == scan_id)
    return int((await db.execute(stmt)).scalar() or 0)


def _scan_to_response(scan: EASMScan, findings_count: int) -> EASMScanResponse:
    return EASMScanResponse(
        id=scan.id,
        project_id=scan.project_id,
        status=scan.status,
        scan_mode=scan.scan_mode,
        modules=list(scan.modules or []),
        started_at=scan.started_at,
        finished_at=scan.finished_at,
        stdout_bytes=scan.stdout_bytes or 0,
        error=scan.error,
        launched_by=scan.launched_by,
        findings_count=findings_count,
    )


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# ---------------------------------------------------------------------------
# POST /api/projects/{project_id}/easm/scans — launch scan
# ---------------------------------------------------------------------------

@router.post(
    "/projects/{project_id}/easm/scans",
    response_model=EASMScanResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def launch_scan(
    project_id: uuid.UUID,
    body: EASMScanCreate,
    request: Request,
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> EASMScanResponse:
    """Launch a BBOT scan for a project.

    Authority (CONTEXT.md §Scan authority matrix):
      passive: Admin, Analyst (global), Lead, Contributor (project)
      active:  Admin (global), Lead (project) only — plus active gate check

    Active-scan gate is defence-in-depth (plan 11-06 is the canonical flip).
    Concurrent-scan race guard (M-5): 409 if another scan is queued/running.
    Semaphore precheck (EASM-09): 503 if Redis counter already at cap.
    """
    # Authority check
    global_role = user.role
    project_rank = _resolve_project_rank(user, project_id)

    if body.scan_mode == "active":
        # Active: Admin (global) or Lead (project) only
        if not (global_role == "Admin" or project_rank >= _LEAD_RANK):
            raise HTTPException(
                status_code=403,
                detail="Only project Leads and global Admins may launch active scans.",
            )
    else:
        # Passive: Admin, Analyst (global), or Contributor+ (project)
        if not (
            global_role in {"Admin", "Analyst"}
            or project_rank >= _CONTRIBUTOR_RANK
        ):
            raise HTTPException(
                status_code=403,
                detail="Insufficient role for passive scan launch.",
            )

    # Load project — also enforces archived/legacy guard
    p = await _load_project_or_404(db, project_id)

    # Module safelist validation (EASM-05 / M-3) — before gate, before enqueue
    ok, invalid = bbot_safelist.validate_modules(body.modules)
    if not ok:
        raise HTTPException(
            status_code=422,
            detail=(
                f"One or more selected modules are not in the stable safelist: {invalid}. "
                "Remove them and retry."
            ),
        )

    # Active-scan gate (EASM-04 defence-in-depth; canonical flip in plan 11-06)
    if body.scan_mode == "active" and not _is_active_gate_valid(p):
        raise HTTPException(
            status_code=403,
            detail="active_scan_gate_not_set_or_expired",
        )

    # M-5 concurrent-scan race prevention: 409 if another scan is queued/running
    existing = (await db.execute(
        select(EASMScan).where(
            EASMScan.project_id == project_id,
            EASMScan.status.in_(("queued", "running")),
        )
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="scan_already_in_progress")

    # Semaphore precheck (EASM-09) — 503 if already at concurrent limit
    # Worker also re-checks; router precheck surfaces the 503 to the UI immediately.
    r = redis_lib.from_url(settings.REDIS_URL)
    try:
        current = int(r.get("bbot:concurrent_scans") or 0)
    except Exception:
        current = 0
    if current >= settings.BBOT_CONCURRENT_LIMIT:
        raise HTTPException(
            status_code=503,
            detail="Scan limit reached. Wait for a running scan to finish before launching another.",
        )

    # Create the scan row (status='queued')
    scan = EASMScan(
        id=uuid.uuid4(),
        project_id=project_id,
        status="queued",
        scan_mode=body.scan_mode,
        modules=list(body.modules),
        started_at=_now(),
        stdout_bytes=0,
        launched_by=user.id,
    )
    db.add(scan)
    await db.commit()
    await db.refresh(scan)

    # Per-mode time_limit (I1): passive → BBOT_PASSIVE_MAX_SECONDS, active → BBOT_ACTIVE_MAX_SECONDS
    # +10% grace period on top of the max wall-clock time.
    mode_seconds = (
        settings.BBOT_PASSIVE_MAX_SECONDS
        if body.scan_mode == "passive"
        else settings.BBOT_ACTIVE_MAX_SECONDS
    )
    time_limit_ms = int(mode_seconds * 1000 * 1.1)
    run_bbot_scan.send_with_options(args=[str(scan.id)], time_limit=time_limit_ms)

    log.info(
        "easm_scan_queued",
        scan_id=str(scan.id),
        project_id=str(project_id),
        mode=body.scan_mode,
        launched_by=user.id,
        time_limit_ms=time_limit_ms,
    )
    return _scan_to_response(scan, 0)


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/easm/scans — list scans
# ---------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/easm/scans",
    response_model=list[EASMScanResponse],
)
async def list_scans(
    project_id: uuid.UUID,
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
    status_filter: str | None = Query(default=None, alias="status"),
    mode_filter: str | None = Query(default=None, alias="mode"),
) -> list[EASMScanResponse]:
    """List scans for a project, newest first. Optional status/mode filters."""
    _require_project_member(user, project_id)

    stmt = select(EASMScan).where(EASMScan.project_id == project_id)
    if status_filter:
        stmt = stmt.where(EASMScan.status == status_filter)
    if mode_filter:
        stmt = stmt.where(EASMScan.scan_mode == mode_filter)
    stmt = stmt.order_by(EASMScan.started_at.desc())

    scans = (await db.execute(stmt)).scalars().all()
    return [_scan_to_response(s, await _findings_count_for(db, s.id)) for s in scans]


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/easm/scans/{scan_id} — single scan
# ---------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/easm/scans/{scan_id}",
    response_model=EASMScanResponse,
)
async def get_scan(
    project_id: uuid.UUID,
    scan_id: uuid.UUID,
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> EASMScanResponse:
    """Return metadata + finding count for a single scan."""
    _require_project_member(user, project_id)

    scan = (await db.execute(
        select(EASMScan).where(
            EASMScan.id == scan_id,
            EASMScan.project_id == project_id,
        )
    )).scalar_one_or_none()
    if scan is None:
        raise HTTPException(status_code=404, detail="scan_not_found")

    fc = await _findings_count_for(db, scan.id)
    return _scan_to_response(scan, fc)


# ---------------------------------------------------------------------------
# DELETE /api/projects/{project_id}/easm/scans/{scan_id} — cancel scan
# ---------------------------------------------------------------------------

@router.delete(
    "/projects/{project_id}/easm/scans/{scan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_scan(
    project_id: uuid.UUID,
    scan_id: uuid.UUID,
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Cancel a running or queued scan.

    Authority: Admin (global), Lead (project), or Contributor who launched the scan.
    Terminal-state scans (finished/failed/cancelled/orphaned) → 204 no-op.
    409 if caller lacks permission and scan is not in a terminal state.
    """
    global_role = user.role
    project_rank = _resolve_project_rank(user, project_id)

    scan = (await db.execute(
        select(EASMScan).where(
            EASMScan.id == scan_id,
            EASMScan.project_id == project_id,
        )
    )).scalar_one_or_none()
    if scan is None:
        raise HTTPException(status_code=404, detail="scan_not_found")

    # Check authority: Admin, Lead, or Contributor-who-launched
    is_owner = scan.launched_by == user.id
    allowed = (
        global_role == "Admin"
        or project_rank >= _LEAD_RANK
        or (project_rank >= _CONTRIBUTOR_RANK and is_owner)
    )
    if not allowed:
        if scan.status in ("queued", "running"):
            raise HTTPException(status_code=403, detail="cannot_cancel_scan")
        # Terminal state — allow 204 silently even without authority
        return Response(status_code=204)

    if scan.status in ("queued", "running"):
        # Best-effort container stop — never crashes the request
        if scan.container_id:
            try:
                bbot_runner.cancel_bbot_container(scan.container_id)
            except Exception:
                log.warning(
                    "easm_cancel_container_failed",
                    scan_id=str(scan_id),
                    container_id=scan.container_id,
                )
        await db.execute(
            sql_update(EASMScan)
            .where(EASMScan.id == scan_id)
            .values(
                status="cancelled",
                finished_at=_now(),
                error="cancelled_by_user",
            )
        )
        await db.commit()
        log.info(
            "easm_scan_cancelled",
            scan_id=str(scan_id),
            project_id=str(project_id),
            cancelled_by=user.id,
        )

    return Response(status_code=204)


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/easm/scans/{scan_id}/diff — EASM-08
# ---------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/easm/scans/{scan_id}/diff",
    response_model=EASMDiffResponse,
)
async def get_scan_diff(
    project_id: uuid.UUID,
    scan_id: uuid.UUID,
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> EASMDiffResponse:
    """Compute NEW / CHANGED / RESOLVED diff vs the previous finished scan.

    Match key is (bbot_event_type, canonical_target) only — module/severity
    differences on the same target produce a CHANGED entry, not a NEW entry.
    Prior scan = next-most-recent *finished* scan for the same project, ordered
    by started_at DESC. Returns empty lists if no prior scan exists.
    """
    _require_project_member(user, project_id)

    this_scan = (await db.execute(
        select(EASMScan).where(
            EASMScan.id == scan_id,
            EASMScan.project_id == project_id,
        )
    )).scalar_one_or_none()
    if this_scan is None:
        raise HTTPException(status_code=404, detail="scan_not_found")

    # Prior scan = next-most-recent finished scan for the same project
    prior_stmt = (
        select(EASMScan)
        .where(
            EASMScan.project_id == project_id,
            EASMScan.id != scan_id,
            EASMScan.status == "finished",
            EASMScan.started_at < this_scan.started_at,
        )
        .order_by(EASMScan.started_at.desc())
        .limit(1)
    )
    prior = (await db.execute(prior_stmt)).scalar_one_or_none()

    if prior is None:
        return EASMDiffResponse(
            this_scan_id=scan_id,
            prior_scan_id=None,
            new=[],
            changed=[],
            resolved=[],
        )

    # Fetch findings for both scans
    this_findings = (await db.execute(
        select(EASMFinding).where(EASMFinding.scan_id == scan_id)
    )).scalars().all()
    prior_findings = (await db.execute(
        select(EASMFinding).where(EASMFinding.scan_id == prior.id)
    )).scalars().all()

    # Build match-key dicts — key is (bbot_event_type, canonical_target)
    this_by_key = {(f.bbot_event_type, f.canonical_target): f for f in this_findings}
    prior_by_key = {(f.bbot_event_type, f.canonical_target): f for f in prior_findings}

    new_keys = this_by_key.keys() - prior_by_key.keys()
    resolved_keys = prior_by_key.keys() - this_by_key.keys()
    common_keys = this_by_key.keys() & prior_by_key.keys()
    changed_keys = [
        k for k in common_keys
        if this_by_key[k].raw_bbot != prior_by_key[k].raw_bbot
    ]

    def _entry(f: EASMFinding) -> EASMDiffEntry:
        return EASMDiffEntry(
            bbot_event_type=f.bbot_event_type,
            canonical_target=f.canonical_target,
            raw_bbot=f.raw_bbot if isinstance(f.raw_bbot, dict) else {},
            module=f.module,
            severity=f.severity,
        )

    return EASMDiffResponse(
        this_scan_id=scan_id,
        prior_scan_id=prior.id,
        new=[_entry(this_by_key[k]) for k in new_keys],
        changed=[
            EASMDiffChangedEntry(
                bbot_event_type=k[0],
                canonical_target=k[1],
                previous=(
                    prior_by_key[k].raw_bbot
                    if isinstance(prior_by_key[k].raw_bbot, dict)
                    else {}
                ),
                current=(
                    this_by_key[k].raw_bbot
                    if isinstance(this_by_key[k].raw_bbot, dict)
                    else {}
                ),
                module=this_by_key[k].module,
            )
            for k in changed_keys
        ],
        resolved=[_entry(prior_by_key[k]) for k in resolved_keys],
    )


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/easm/findings — list findings
# ---------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/easm/findings",
    response_model=list[EASMFindingResponse],
)
async def list_findings(
    project_id: uuid.UUID,
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
    bbot_type: str | None = Query(default=None, alias="type"),
    module: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    lifecycle: str | None = Query(default=None),
    include_dismissed: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[EASMFindingResponse]:
    """List findings for a project with optional filters.

    By default, dismissed findings are hidden. Pass include_dismissed=true to
    include them. If lifecycle filter is specified, include_dismissed is ignored.
    """
    _require_project_member(user, project_id)

    stmt = select(EASMFinding).where(EASMFinding.project_id == project_id)
    if bbot_type:
        stmt = stmt.where(EASMFinding.bbot_event_type == bbot_type)
    if module:
        stmt = stmt.where(EASMFinding.module == module)
    if severity:
        stmt = stmt.where(EASMFinding.severity == severity)
    if lifecycle:
        stmt = stmt.where(EASMFinding.lifecycle_status == lifecycle)
    elif not include_dismissed:
        stmt = stmt.where(EASMFinding.lifecycle_status != "dismissed")
    stmt = stmt.order_by(EASMFinding.last_seen.desc()).limit(limit).offset(offset)

    rows = (await db.execute(stmt)).scalars().all()
    return [EASMFindingResponse.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# PATCH /api/projects/{project_id}/easm/findings/{finding_id} — lifecycle patch
# ---------------------------------------------------------------------------

@router.patch(
    "/projects/{project_id}/easm/findings/{finding_id}",
    response_model=EASMFindingResponse,
)
async def patch_finding(
    project_id: uuid.UUID,
    finding_id: uuid.UUID,
    body: EASMFindingLifecyclePatch,
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> EASMFindingResponse:
    """Update finding lifecycle status (confirm / dismiss / watchlist / new).

    Observer blocked — requires Contributor+, global Analyst, or global Admin.
    'dismissed' sets dismiss_until = NOW() + 30d.
    'new' clears dismiss_until.
    """
    global_role = user.role
    project_rank = _resolve_project_rank(user, project_id)

    # Observer blocked from PATCH (authority matrix + UI-SPEC canonical copy)
    if not (
        global_role in {"Admin", "Analyst"}
        or project_rank >= _CONTRIBUTOR_RANK
    ):
        raise HTTPException(
            status_code=403,
            detail="Observers cannot modify finding status.",
        )

    f = (await db.execute(
        select(EASMFinding).where(
            EASMFinding.id == finding_id,
            EASMFinding.project_id == project_id,
        )
    )).scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=404, detail="finding_not_found")

    values: dict = {"lifecycle_status": body.lifecycle_status}
    if body.lifecycle_status == "dismissed":
        values["dismiss_until"] = _now() + datetime.timedelta(days=30)
    elif body.lifecycle_status == "new":
        values["dismiss_until"] = None

    await db.execute(
        sql_update(EASMFinding).where(EASMFinding.id == finding_id).values(**values)
    )
    await db.commit()

    f = (await db.execute(
        select(EASMFinding).where(EASMFinding.id == finding_id)
    )).scalar_one()
    return EASMFindingResponse.model_validate(f)


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/easm/scans/{scan_id}/findings — scan-scoped findings
# ---------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/easm/scans/{scan_id}/findings",
    response_model=list[EASMFindingResponse],
)
async def list_scan_findings(
    project_id: uuid.UUID,
    scan_id: uuid.UUID,
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[EASMFindingResponse]:
    """List findings scoped to a single scan (for scan-detail page)."""
    _require_project_member(user, project_id)

    # Verify the scan belongs to this project
    scan = (await db.execute(
        select(EASMScan).where(
            EASMScan.id == scan_id,
            EASMScan.project_id == project_id,
        )
    )).scalar_one_or_none()
    if scan is None:
        raise HTTPException(status_code=404, detail="scan_not_found")

    stmt = (
        select(EASMFinding)
        .where(EASMFinding.scan_id == scan_id)
        .order_by(EASMFinding.last_seen.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [EASMFindingResponse.model_validate(r) for r in rows]
