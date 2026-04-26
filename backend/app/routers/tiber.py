"""FastAPI router for the TIBER report generation surface — Phase 18 / TIBER-01..03, AI-08.

All endpoints are under prefix /api/projects/{project_id}/tiber.

Role gates:
  Member+   — read (GET) endpoints
  Lead+     — write/create/publish/export endpoints
  Admin     — archive, restore

State machine:
  draft → published  (Lead+ POST /publish)
  published → archived (Admin POST /archive)
  archived → draft   (Admin POST /restore)
  any state → clone  (Member+ POST /clone → creates new draft)

PATCH /reports/{id} returns 409 Conflict when state == 'published'.
POST /archive returns 409 Conflict when state != 'published'.
POST /restore returns 409 Conflict when state != 'archived'.

Export list (GET /exports) explicitly excludes content_bytea column (TOAST
avoidance — H-5). content_bytea is only fetched on explicit download requests:
GET /exports/{export_id}/download.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_auth, require_admin
from app.models.projects import ProjectRole
from app.models.tiber import TiberReport, TiberActorProfile, TiberScenario, ReportExport
from app.schemas.tiber import (
    TiberReportCreate,
    TiberReportPatch,
    TiberReportRead,
    ActorProfileCreate,
    ActorProfileRead,
    ScenarioPatch,
    ScenarioRead,
    ExportCreate,
    ExportRead,
    RefreshDiffResponse,
    RefreshDiffRow,
    RefreshDiffApply,
    ReportFormat,
)
from app.security.jwt import AuthUser
from app.security.project_membership import require_project_membership

log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/projects/{project_id}/tiber",
    tags=["tiber"],
)

# ---------------------------------------------------------------------------
# MIME map for download endpoint
# ---------------------------------------------------------------------------

MIME_MAP: dict[str, str] = {
    "markdown": "text/markdown",
    "pdf": "application/pdf",
    "stix": "application/json",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_report(
    db: AsyncSession,
    report_id: uuid.UUID,
    project_id: uuid.UUID,
) -> TiberReport:
    """Load a TiberReport and verify it belongs to project_id. 404 if not found."""
    report = await db.get(TiberReport, report_id)
    if report is None or report.project_id != project_id:
        raise HTTPException(status_code=404, detail="report_not_found")
    return report


async def _get_actor(
    db: AsyncSession,
    actor_id: uuid.UUID,
    report_id: uuid.UUID,
    project_id: uuid.UUID,
) -> TiberActorProfile:
    """Load TiberActorProfile scoped to report_id and project_id."""
    actor = await db.get(TiberActorProfile, actor_id)
    if actor is None or actor.tiber_report_id != report_id or actor.project_id != project_id:
        raise HTTPException(status_code=404, detail="actor_not_found")
    return actor


async def _get_scenario(
    db: AsyncSession,
    scenario_id: uuid.UUID,
    report_id: uuid.UUID,
    project_id: uuid.UUID,
) -> TiberScenario:
    """Load TiberScenario scoped to report_id and project_id."""
    scenario = await db.get(TiberScenario, scenario_id)
    if scenario is None or scenario.tiber_report_id != report_id or scenario.project_id != project_id:
        raise HTTPException(status_code=404, detail="scenario_not_found")
    return scenario


def _run_gates(report: TiberReport, actors: list, scenarios: list) -> None:
    """Run completeness_check and scenario_gate_check; raise 422 if gates fail.

    Raises HTTPException(422) with combined gate failure details.
    """
    from app.services.tiber.validators import completeness_check, scenario_gate_check  # noqa: PLC0415

    # Completeness check requires report with .actors and .scenarios accessible;
    # attach lists temporarily for duck-typing compatibility.
    class _ReportProxy:
        pass

    proxy = _ReportProxy()
    for attr in (
        "engagement_window_start", "engagement_window_end",
        "in_scope_assets", "out_of_scope_assets",
        "aia_summary_text", "aia_recommendations",
        "tl_top_events", "tl_analyst_narrative",
        "scenario_x_narrative",
    ):
        setattr(proxy, attr, getattr(report, attr, None))
    proxy.actors = actors  # type: ignore[attr-defined]
    proxy.scenarios = scenarios  # type: ignore[attr-defined]

    missing_sections = completeness_check(proxy)
    gate_errors = scenario_gate_check(scenarios)

    if missing_sections or gate_errors:
        raise HTTPException(
            status_code=422,
            detail={
                "missing_sections": missing_sections,
                "gate_errors": gate_errors,
            },
        )


# ---------------------------------------------------------------------------
# POST /api/projects/{project_id}/tiber/reports — create report (Lead+)
# ---------------------------------------------------------------------------


@router.post("/reports", status_code=201, response_model=TiberReportRead)
async def create_report(
    project_id: uuid.UUID,
    body: TiberReportCreate,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> TiberReportRead:
    """Create a new TIBER report draft with auto-populated sections.

    Auto-populates:
      - Threat Landscape (top-N scored events)
      - Actor Profiles (top-6 by relevance via graph traversal)
      - Scenarios longlist (up to 6 from TTP analysis)
      - Actionable Intelligence Assessment (summary + top-3 high-tier events)
    """
    from app.services.tiber.auto_populate import (  # noqa: PLC0415
        populate_threat_landscape,
        populate_actor_profiles,
        populate_scenarios_longlist,
        populate_actionable_intelligence,
    )

    try:
        creator_id = uuid.UUID(user.id)
    except (ValueError, AttributeError):
        creator_id = None

    report = TiberReport(
        id=uuid.uuid4(),
        project_id=project_id,
        title=body.title,
        cbest_mode=body.cbest_mode,
        state="draft",
        created_by_user_id=creator_id,
    )
    db.add(report)
    await db.flush()

    # --- Auto-populate 4 sections ---
    # 1. Threat Landscape — top-N events
    try:
        tl_events = await populate_threat_landscape(db, project_id, top_n=20)
        report.tl_top_events = [
            {
                "id": str(e.id),
                "title": e.title or "",
                "score": float(e.score) if e.score is not None else None,
                "stix_type": e.stix_type or "",
                "observed_at": e.observed_at.isoformat() if e.observed_at else None,
                "project_id": str(e.project_id),
            }
            for e in tl_events
        ]
    except Exception as exc:  # noqa: BLE001
        log.warning("tiber_auto_populate_tl_failed project_id=%s error=%r", project_id, exc)
        report.tl_top_events = []

    # 2. Actor Profiles
    try:
        actor_results = await populate_actor_profiles(db, project_id, top_n=6)
        for ap in actor_results:
            db.add(TiberActorProfile(
                id=uuid.uuid4(),
                tiber_report_id=report.id,
                project_id=project_id,
                name=ap.name,
                motivation=ap.motivation,
                capability_assessment=ap.capability_assessment,
                relevance_to_target=ap.relevance_to_target,
                source_event_ids=ap.source_event_ids,
            ))
    except Exception as exc:  # noqa: BLE001
        log.warning("tiber_auto_populate_ap_failed project_id=%s error=%r", project_id, exc)

    # 3. Scenarios longlist
    try:
        scenario_results = await populate_scenarios_longlist(db, project_id, max_count=6)
        for i, sl in enumerate(scenario_results):
            db.add(TiberScenario(
                id=uuid.uuid4(),
                tiber_report_id=report.id,
                project_id=project_id,
                attack_technique_id=sl.attack_technique_id,
                sort_order=i,
            ))
    except Exception as exc:  # noqa: BLE001
        log.warning("tiber_auto_populate_sl_failed project_id=%s error=%r", project_id, exc)

    # 4. Actionable Intelligence
    try:
        aia = await populate_actionable_intelligence(db, project_id)
        report.aia_summary_text = aia.summary_text
    except Exception as exc:  # noqa: BLE001
        log.warning("tiber_auto_populate_aia_failed project_id=%s error=%r", project_id, exc)

    await db.commit()
    await db.refresh(report)
    log.info("tiber_report_created report_id=%s project_id=%s", report.id, project_id)
    return TiberReportRead.model_validate(report)


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/tiber/reports — list reports (Member+)
# ---------------------------------------------------------------------------


@router.get("/reports", response_model=list[TiberReportRead])
async def list_reports(
    project_id: uuid.UUID,
    status_filter: Literal["draft", "published", "archived", "all"] = Query("all", alias="status"),
    include_archived: bool = Query(False),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    db: AsyncSession = Depends(get_session),
) -> list[TiberReportRead]:
    """List TIBER reports for a project.

    Defaults: status=all, include_archived=False (hides archived).
    """
    q = select(TiberReport).where(TiberReport.project_id == project_id)
    if status_filter != "all":
        q = q.where(TiberReport.state == status_filter)
    elif not include_archived:
        q = q.where(TiberReport.state != "archived")
    q = q.order_by(TiberReport.updated_at.desc())
    rows = (await db.execute(q)).scalars().all()
    return [TiberReportRead.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/tiber/reports/{report_id} — get report (Member+)
# ---------------------------------------------------------------------------


@router.get("/reports/{report_id}", response_model=TiberReportRead)
async def get_report(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    db: AsyncSession = Depends(get_session),
) -> TiberReportRead:
    """Return a single TIBER report by ID."""
    report = await _get_report(db, report_id, project_id)
    return TiberReportRead.model_validate(report)


# ---------------------------------------------------------------------------
# PATCH /api/projects/{project_id}/tiber/reports/{report_id} — update (Lead+)
# ---------------------------------------------------------------------------


@router.patch("/reports/{report_id}", response_model=TiberReportRead)
async def patch_report(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    body: TiberReportPatch,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> TiberReportRead:
    """Partially update a TIBER report.

    Returns 409 Conflict when the report state is 'published' — published
    reports are immutable; use POST /clone to create an editable copy.
    """
    report = await _get_report(db, report_id, project_id)
    if report.state == "published":
        raise HTTPException(
            status_code=409,
            detail="report_published_immutable — use POST /clone to create an editable draft",
        )
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(report, key, value)
    report.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(report)
    log.info("tiber_report_patched report_id=%s project_id=%s by=%s", report_id, project_id, user.id)
    return TiberReportRead.model_validate(report)


# ---------------------------------------------------------------------------
# POST /reports/{report_id}/publish — publish report (Lead+)
# ---------------------------------------------------------------------------


@router.post("/reports/{report_id}/publish", response_model=TiberReportRead)
async def publish_report(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> TiberReportRead:
    """Publish a TIBER report.

    Runs completeness_check + scenario_gate_check. If either fails, returns 422
    with detail {missing_sections: ..., gate_errors: ...}.
    Only transitions from state='draft'; raises 409 for any other state.
    """
    report = await _get_report(db, report_id, project_id)
    if report.state != "draft":
        raise HTTPException(
            status_code=409,
            detail=f"cannot_publish_from_state:{report.state}",
        )

    actors = list((await db.execute(
        select(TiberActorProfile).where(TiberActorProfile.tiber_report_id == report_id)
    )).scalars().all())
    scenarios = list((await db.execute(
        select(TiberScenario).where(TiberScenario.tiber_report_id == report_id)
    )).scalars().all())

    _run_gates(report, actors, scenarios)

    report.state = "published"
    report.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(report)
    log.info("tiber_report_published report_id=%s project_id=%s by=%s", report_id, project_id, user.id)
    return TiberReportRead.model_validate(report)


# ---------------------------------------------------------------------------
# POST /reports/{report_id}/archive — archive report (Admin only)
# ---------------------------------------------------------------------------


@router.post("/reports/{report_id}/archive", response_model=TiberReportRead)
async def archive_report(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    _admin: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> TiberReportRead:
    """Archive a TIBER report. Admin only. Rejects with 409 if not currently 'published'."""
    report = await _get_report(db, report_id, project_id)
    if report.state != "published":
        raise HTTPException(
            status_code=409,
            detail=f"cannot_archive_from_state:{report.state}",
        )
    report.state = "archived"
    report.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(report)
    log.info("tiber_report_archived report_id=%s project_id=%s by=%s", report_id, project_id, _admin.id)
    return TiberReportRead.model_validate(report)


# ---------------------------------------------------------------------------
# POST /reports/{report_id}/restore — restore to draft (Admin only)
# ---------------------------------------------------------------------------


@router.post("/reports/{report_id}/restore", response_model=TiberReportRead)
async def restore_report(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    _admin: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
) -> TiberReportRead:
    """Restore an archived TIBER report to draft state. Admin only.

    Implements the archived→draft locked transition from CONTEXT.md §Report state machine.
    Rejects with 409 Conflict if the report is not currently 'archived'.
    """
    report = await _get_report(db, report_id, project_id)
    if report.state != "archived":
        raise HTTPException(
            status_code=409,
            detail=f"cannot_restore_from_state:{report.state}",
        )
    report.state = "draft"
    report.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(report)
    log.info("tiber_report_restored report_id=%s project_id=%s by=%s", report_id, project_id, _admin.id)
    return TiberReportRead.model_validate(report)


# ---------------------------------------------------------------------------
# POST /reports/{report_id}/clone — clone to new draft (Member+)
# ---------------------------------------------------------------------------


@router.post("/reports/{report_id}/clone", status_code=201, response_model=TiberReportRead)
async def clone_report(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> TiberReportRead:
    """Clone a TIBER report into a new fresh draft.

    Copies all section fields + actor profiles + scenarios from the source report.
    The new report gets state='draft' and a fresh ID — original report unchanged.
    Preserves audit trail: original published row remains intact.
    """
    source = await _get_report(db, report_id, project_id)

    try:
        creator_id = uuid.UUID(user.id)
    except (ValueError, AttributeError):
        creator_id = None

    # Deep copy report fields
    clone = TiberReport(
        id=uuid.uuid4(),
        project_id=project_id,
        title=f"{source.title} (Clone)",
        cbest_mode=source.cbest_mode,
        state="draft",
        engagement_window_start=source.engagement_window_start,
        engagement_window_end=source.engagement_window_end,
        in_scope_assets=list(source.in_scope_assets),
        out_of_scope_assets=list(source.out_of_scope_assets),
        aia_summary_text=source.aia_summary_text,
        aia_recommendations=list(source.aia_recommendations),
        tl_top_events=list(source.tl_top_events),
        tl_analyst_narrative=source.tl_analyst_narrative,
        tl_top_events_count=source.tl_top_events_count,
        scenario_x_narrative=source.scenario_x_narrative,
        created_by_user_id=creator_id,
    )
    db.add(clone)
    await db.flush()

    # Copy actor profiles
    source_actors = (await db.execute(
        select(TiberActorProfile).where(TiberActorProfile.tiber_report_id == source.id)
    )).scalars().all()
    actor_id_map: dict[uuid.UUID, uuid.UUID] = {}
    for ap in source_actors:
        new_actor_id = uuid.uuid4()
        actor_id_map[ap.id] = new_actor_id
        db.add(TiberActorProfile(
            id=new_actor_id,
            tiber_report_id=clone.id,
            project_id=project_id,
            name=ap.name,
            motivation=ap.motivation,
            capability_assessment=ap.capability_assessment,
            relevance_to_target=ap.relevance_to_target,
            source_event_ids=list(ap.source_event_ids),
        ))

    # Copy scenarios — remap actor_id refs to new actor IDs
    source_scenarios = (await db.execute(
        select(TiberScenario).where(TiberScenario.tiber_report_id == source.id)
    )).scalars().all()
    for sc in source_scenarios:
        new_actor_ref = actor_id_map.get(sc.actor_id) if sc.actor_id else None
        db.add(TiberScenario(
            id=uuid.uuid4(),
            tiber_report_id=clone.id,
            project_id=project_id,
            actor_id=new_actor_ref,
            cif_or_cbs_label=sc.cif_or_cbs_label,
            objective_type=sc.objective_type,
            attack_technique_id=sc.attack_technique_id,
            procedure_text=sc.procedure_text,
            selected_for_inclusion=sc.selected_for_inclusion,
            ai_draft_narrative=sc.ai_draft_narrative,
            ai_draft_metadata=sc.ai_draft_metadata,
            sort_order=sc.sort_order,
        ))

    await db.commit()
    await db.refresh(clone)
    log.info(
        "tiber_report_cloned source_id=%s clone_id=%s project_id=%s by=%s",
        source.id, clone.id, project_id, user.id,
    )
    return TiberReportRead.model_validate(clone)


# ---------------------------------------------------------------------------
# POST /reports/{report_id}/sections/{section}/refresh — section refresh diff (Lead+)
# ---------------------------------------------------------------------------


@router.post(
    "/reports/{report_id}/sections/{section}/refresh",
    response_model=RefreshDiffResponse,
)
async def refresh_section(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    section: Literal["actionable_intelligence", "threat_landscape", "actor_profiles", "scenarios"],
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    db: AsyncSession = Depends(get_session),
) -> RefreshDiffResponse:
    """Return a diff of current vs freshly auto-populated section content.

    Does NOT write anything — returns side-by-side diff rows for analyst review.
    Call POST .../sections/{section}/apply to selectively apply accepted rows.
    """
    from app.services.tiber.auto_populate import (  # noqa: PLC0415
        populate_threat_landscape,
        populate_actor_profiles,
        populate_scenarios_longlist,
        populate_actionable_intelligence,
    )

    report = await _get_report(db, report_id, project_id)
    diff_rows: list[RefreshDiffRow] = []

    if section == "threat_landscape":
        new_events = await populate_threat_landscape(db, project_id, top_n=report.tl_top_events_count)
        new_events_list = [
            {
                "id": str(e.id),
                "title": e.title or "",
                "score": float(e.score) if e.score is not None else None,
                "stix_type": e.stix_type or "",
                "observed_at": e.observed_at.isoformat() if e.observed_at else None,
                "project_id": str(e.project_id),
            }
            for e in new_events
        ]
        diff_rows.append(RefreshDiffRow(
            field_path="tl_top_events",
            current_value=report.tl_top_events,
            new_value=new_events_list,
        ))

    elif section == "actionable_intelligence":
        aia = await populate_actionable_intelligence(db, project_id)
        diff_rows.append(RefreshDiffRow(
            field_path="aia_summary_text",
            current_value=report.aia_summary_text,
            new_value=aia.summary_text,
        ))

    elif section == "actor_profiles":
        actor_results = await populate_actor_profiles(db, project_id, top_n=6)
        new_actors = [
            {
                "name": ap.name,
                "motivation": ap.motivation,
                "capability_assessment": ap.capability_assessment,
                "relevance_to_target": ap.relevance_to_target,
                "source_event_ids": ap.source_event_ids,
            }
            for ap in actor_results
        ]
        current_actors = (await db.execute(
            select(TiberActorProfile).where(TiberActorProfile.tiber_report_id == report_id)
        )).scalars().all()
        current_list = [
            {
                "id": str(a.id),
                "name": a.name,
                "motivation": a.motivation,
                "capability_assessment": a.capability_assessment,
                "relevance_to_target": a.relevance_to_target,
            }
            for a in current_actors
        ]
        diff_rows.append(RefreshDiffRow(
            field_path="actor_profiles",
            current_value=current_list,
            new_value=new_actors,
        ))

    elif section == "scenarios":
        scenario_results = await populate_scenarios_longlist(db, project_id, max_count=6)
        new_scenarios = [
            {
                "attack_technique_id": sl.attack_technique_id,
                "candidate_procedure_text": sl.candidate_procedure_text,
            }
            for sl in scenario_results
        ]
        current_scenarios = (await db.execute(
            select(TiberScenario).where(TiberScenario.tiber_report_id == report_id)
        )).scalars().all()
        current_list = [
            {
                "id": str(s.id),
                "attack_technique_id": s.attack_technique_id,
                "procedure_text": s.procedure_text,
            }
            for s in current_scenarios
        ]
        diff_rows.append(RefreshDiffRow(
            field_path="scenarios",
            current_value=current_list,
            new_value=new_scenarios,
        ))

    return RefreshDiffResponse(section=section, rows=diff_rows)


# ---------------------------------------------------------------------------
# POST /reports/{report_id}/sections/{section}/apply — apply diff selections (Lead+)
# ---------------------------------------------------------------------------


@router.post("/reports/{report_id}/sections/{section}/apply", response_model=TiberReportRead)
async def apply_section_refresh(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    section: Literal["actionable_intelligence", "threat_landscape", "actor_profiles", "scenarios"],
    body: RefreshDiffApply,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> TiberReportRead:
    """Apply accepted diff field paths from a section refresh.

    Only fields listed in body.accepted_field_paths are written — no silent
    overwrite of analyst edits for unaccepted fields.
    """
    from app.services.tiber.auto_populate import (  # noqa: PLC0415
        populate_threat_landscape,
        populate_actionable_intelligence,
    )

    report = await _get_report(db, report_id, project_id)

    if "tl_top_events" in body.accepted_field_paths and section == "threat_landscape":
        new_events = await populate_threat_landscape(db, project_id, top_n=report.tl_top_events_count)
        report.tl_top_events = [
            {
                "id": str(e.id),
                "title": e.title or "",
                "score": float(e.score) if e.score is not None else None,
                "stix_type": e.stix_type or "",
                "observed_at": e.observed_at.isoformat() if e.observed_at else None,
                "project_id": str(e.project_id),
            }
            for e in new_events
        ]

    if "aia_summary_text" in body.accepted_field_paths and section == "actionable_intelligence":
        aia = await populate_actionable_intelligence(db, project_id)
        report.aia_summary_text = aia.summary_text

    report.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(report)
    return TiberReportRead.model_validate(report)


# ---------------------------------------------------------------------------
# Actor CRUD
# ---------------------------------------------------------------------------


@router.get("/reports/{report_id}/actors", response_model=list[ActorProfileRead])
async def list_actors(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    db: AsyncSession = Depends(get_session),
) -> list[ActorProfileRead]:
    """List actor profiles for a TIBER report."""
    await _get_report(db, report_id, project_id)
    rows = (await db.execute(
        select(TiberActorProfile)
        .where(TiberActorProfile.tiber_report_id == report_id)
        .order_by(TiberActorProfile.created_at.asc())
    )).scalars().all()
    return [ActorProfileRead.model_validate(r) for r in rows]


@router.post("/reports/{report_id}/actors", status_code=201, response_model=ActorProfileRead)
async def create_actor(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    body: ActorProfileCreate,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    db: AsyncSession = Depends(get_session),
) -> ActorProfileRead:
    """Add an actor profile to a TIBER report."""
    await _get_report(db, report_id, project_id)
    actor = TiberActorProfile(
        id=uuid.uuid4(),
        tiber_report_id=report_id,
        project_id=project_id,
        name=body.name,
        motivation=body.motivation,
        capability_assessment=body.capability_assessment,
        relevance_to_target=body.relevance_to_target,
        source_event_ids=[],
    )
    db.add(actor)
    await db.commit()
    await db.refresh(actor)
    return ActorProfileRead.model_validate(actor)


@router.patch("/reports/{report_id}/actors/{actor_id}", response_model=ActorProfileRead)
async def patch_actor(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    actor_id: uuid.UUID,
    body: ActorProfileCreate,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    db: AsyncSession = Depends(get_session),
) -> ActorProfileRead:
    """Update an actor profile."""
    actor = await _get_actor(db, actor_id, report_id, project_id)
    if body.name is not None:
        actor.name = body.name
    if body.motivation is not None:
        actor.motivation = body.motivation
    if body.capability_assessment is not None:
        actor.capability_assessment = body.capability_assessment
    if body.relevance_to_target is not None:
        actor.relevance_to_target = body.relevance_to_target
    await db.commit()
    await db.refresh(actor)
    return ActorProfileRead.model_validate(actor)


@router.delete("/reports/{report_id}/actors/{actor_id}", status_code=204)
async def delete_actor(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    actor_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Delete an actor profile from a TIBER report."""
    actor = await _get_actor(db, actor_id, report_id, project_id)
    await db.delete(actor)
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Scenario CRUD
# ---------------------------------------------------------------------------


@router.get("/reports/{report_id}/scenarios", response_model=list[ScenarioRead])
async def list_scenarios(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    db: AsyncSession = Depends(get_session),
) -> list[ScenarioRead]:
    """List all scenarios in the TIBER report longlist."""
    await _get_report(db, report_id, project_id)
    rows = (await db.execute(
        select(TiberScenario)
        .where(TiberScenario.tiber_report_id == report_id)
        .order_by(TiberScenario.sort_order.asc(), TiberScenario.created_at.asc())
    )).scalars().all()
    return [ScenarioRead.model_validate(r) for r in rows]


@router.post("/reports/{report_id}/scenarios", status_code=201, response_model=ScenarioRead)
async def create_scenario(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    body: ScenarioPatch,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    db: AsyncSession = Depends(get_session),
) -> ScenarioRead:
    """Add a scenario to the TIBER report longlist."""
    await _get_report(db, report_id, project_id)
    scenario = TiberScenario(
        id=uuid.uuid4(),
        tiber_report_id=report_id,
        project_id=project_id,
        actor_id=body.actor_id,
        cif_or_cbs_label=body.cif_or_cbs_label,
        objective_type=body.objective_type.value if body.objective_type else None,
        attack_technique_id=body.attack_technique_id,
        procedure_text=body.procedure_text,
        selected_for_inclusion=body.selected_for_inclusion or False,
        sort_order=body.sort_order or 0,
    )
    db.add(scenario)
    await db.commit()
    await db.refresh(scenario)
    return ScenarioRead.model_validate(scenario)


@router.patch("/reports/{report_id}/scenarios/{scenario_id}", response_model=ScenarioRead)
async def patch_scenario(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    scenario_id: uuid.UUID,
    body: ScenarioPatch,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> ScenarioRead:
    """Partial-update a scenario. Auto-saves per stepper step.

    When analyst edits ai_draft_narrative (and it was AI-drafted), writes
    ai_draft_metadata with edited_by + edited_at (AI-08 audit badge).
    """
    scenario = await _get_scenario(db, scenario_id, report_id, project_id)
    data = body.model_dump(exclude_unset=True)

    # AI-08: Track analyst edits to AI-drafted narrative
    if "ai_draft_narrative" in data and scenario.ai_draft_metadata is not None:
        meta = dict(scenario.ai_draft_metadata)
        meta["edited_by"] = user.id
        meta["edited_at"] = datetime.now(timezone.utc).isoformat()
        scenario.ai_draft_metadata = meta

    for key, value in data.items():
        if key == "objective_type" and value is not None:
            setattr(scenario, key, value.value if hasattr(value, "value") else value)
        else:
            setattr(scenario, key, value)

    scenario.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(scenario)
    return ScenarioRead.model_validate(scenario)


@router.delete("/reports/{report_id}/scenarios/{scenario_id}", status_code=204)
async def delete_scenario(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    scenario_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a scenario from the TIBER report longlist."""
    scenario = await _get_scenario(db, scenario_id, report_id, project_id)
    await db.delete(scenario)
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# POST /reports/{report_id}/scenarios/{scenario_id}/draft-narrative (Lead+)
# ---------------------------------------------------------------------------


@router.post(
    "/reports/{report_id}/scenarios/{scenario_id}/draft-narrative",
    status_code=202,
)
async def draft_narrative(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    scenario_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Enqueue AI narrative draft for a scenario.

    Enqueues ai_draft_scenario_narrative on the `ai` queue (Phase 17).
    Returns {job_id} 202 — SSE consumer at existing /api/ai/jobs/{job_id}/stream.

    Also stores the job:project association in Redis for stream auth.
    """
    from app.workers.ai import ai_draft_scenario_narrative  # noqa: PLC0415

    scenario = await _get_scenario(db, scenario_id, report_id, project_id)

    job_id = str(uuid.uuid4())

    # Store project association for SSE stream auth
    try:
        from app.services.redis_client import get_redis  # noqa: PLC0415
        redis = await get_redis()
        await redis.set(f"ai:job:{job_id}:project", str(project_id), ex=3600)
    except Exception as exc:  # noqa: BLE001
        log.warning("tiber_draft_narrative_redis_set_failed job_id=%s error=%r", job_id, exc)

    # Mark scenario as having an AI draft in progress
    if scenario.ai_draft_metadata is None:
        scenario.ai_draft_metadata = {"ai_drafted": True}
    await db.commit()

    ai_draft_scenario_narrative.send(job_id, str(scenario_id), str(project_id), str(user.id))
    log.info(
        "tiber_draft_narrative_enqueued job_id=%s scenario_id=%s project_id=%s by=%s",
        job_id, scenario_id, project_id, user.id,
    )
    return {"job_id": job_id}


# ---------------------------------------------------------------------------
# Export endpoints
# ---------------------------------------------------------------------------


@router.post("/reports/{report_id}/exports", status_code=202)
async def create_export(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    body: ExportCreate,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Enqueue a report export.

    Runs completeness_check + scenario_gate_check — rejects with 422 if gates fail.
    Enqueues generate_report_actor on the `reports` queue (Phase 18).
    Returns {export_id, status: 'queued', format} 202.
    """
    from app.workers.reports import generate_report_actor  # noqa: PLC0415

    report = await _get_report(db, report_id, project_id)
    actors = list((await db.execute(
        select(TiberActorProfile).where(TiberActorProfile.tiber_report_id == report_id)
    )).scalars().all())
    scenarios = list((await db.execute(
        select(TiberScenario).where(TiberScenario.tiber_report_id == report_id)
    )).scalars().all())

    _run_gates(report, actors, scenarios)

    export_id = str(uuid.uuid4())
    generate_report_actor.send(str(report_id), str(project_id), body.format.value, str(user.id))
    log.info(
        "tiber_export_enqueued export_id=%s report_id=%s project_id=%s format=%s by=%s",
        export_id, report_id, project_id, body.format.value, user.id,
    )
    return {"export_id": export_id, "status": "queued", "format": body.format.value}


@router.get("/reports/{report_id}/exports", response_model=list[ExportRead])
async def list_exports(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    format: ReportFormat | None = Query(None),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    db: AsyncSession = Depends(get_session),
) -> list[ExportRead]:
    """List export history for a report.

    IMPORTANT: This query explicitly excludes content_bytea to avoid TOAST
    decompression on every row in the history list (H-5 TOAST avoidance).
    content_bytea is only fetched by GET /exports/{export_id}/download.
    """
    # Explicitly select only metadata columns — NEVER include content_bytea here
    cols = [
        ReportExport.id,
        ReportExport.tiber_report_id,
        ReportExport.project_id,
        ReportExport.format,
        ReportExport.version_number,
        ReportExport.filename,
        ReportExport.generated_at,
        ReportExport.generated_by_user_id,
        ReportExport.report_state_at_export,
    ]
    q = (
        select(*cols)
        .where(
            ReportExport.tiber_report_id == report_id,
            ReportExport.project_id == project_id,
        )
    )
    if format is not None:
        q = q.where(ReportExport.format == format.value)
    q = q.order_by(ReportExport.generated_at.desc())
    rows = (await db.execute(q)).all()
    return [ExportRead.model_validate(r._asdict()) for r in rows]


@router.get("/reports/{report_id}/exports/latest")
async def latest_export(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    format: ReportFormat | None = Query(None),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Return the latest export metadata or queue status for a given format.

    Returns {status: 'ready', ...ExportRead} if export exists,
    or {status: 'none'} if no export has been generated yet.
    """
    cols = [
        ReportExport.id,
        ReportExport.tiber_report_id,
        ReportExport.project_id,
        ReportExport.format,
        ReportExport.version_number,
        ReportExport.filename,
        ReportExport.generated_at,
        ReportExport.generated_by_user_id,
        ReportExport.report_state_at_export,
    ]
    q = (
        select(*cols)
        .where(
            ReportExport.tiber_report_id == report_id,
            ReportExport.project_id == project_id,
        )
    )
    if format is not None:
        q = q.where(ReportExport.format == format.value)
    q = q.order_by(ReportExport.generated_at.desc()).limit(1)
    row = (await db.execute(q)).first()
    if row is None:
        return {"status": "none"}
    data = row._asdict()
    data["status"] = "ready"
    return data


@router.get("/reports/{report_id}/exports/{export_id}/download")
async def download_export(
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    export_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Stream a report export BYTEA blob with Content-Disposition attachment.

    This is the ONLY endpoint that fetches content_bytea — all other export
    endpoints exclude the BYTEA column (H-5 TOAST avoidance).

    MIME types:
      markdown → text/markdown
      pdf      → application/pdf
      stix     → application/json
    """
    # Only here do we fetch content_bytea — explicit download request
    row = await db.get(ReportExport, export_id)
    if row is None or row.project_id != project_id or row.tiber_report_id != report_id:
        raise HTTPException(status_code=404, detail="export_not_found")
    mime = MIME_MAP.get(row.format, "application/octet-stream")
    return Response(
        content=row.content_bytea,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{row.filename}"'},
    )
