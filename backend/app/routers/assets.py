"""/api/projects/{project_id}/assets — project asset surface.

Read endpoints (list/summary/detail) plus write (PATCH note) + export (CSV/JSON):
  GET    /                       — list (paginated, filterable)
  GET    /summary                — 7-bucket count summary
  GET    /{asset_id}             — detail (findings + promoted events + note)
  PATCH  /{asset_id}/note        — upsert note (Contributor+ / global Admin|Analyst)
  GET    /export?format=csv|json — streaming export, 413 when >50k matched rows

Router registered via main.py include_router(assets.router) (04b).
"""
from __future__ import annotations

import csv
import io
import json as _json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

# Locked canonical imports (verified during revision against working tree):
from app.database import get_session
from app.middleware.auth import require_auth
from app.models.assets import AssetNote
from app.models.easm import EASMFinding, EASMScan
from app.models.events import Event
from app.models.projects import LEGACY_PROJECT_ID, Project, ProjectRole
from app.schemas.assets import (
    AssetDetail,
    AssetExportFormat,
    AssetFinding,
    AssetListResponse,
    AssetNotePatch,
    AssetNoteRead,
    AssetPromotedEvent,
    AssetRow,
    AssetScope,
    AssetSummary,
    StaleFilter,
    SUMMARY_BUCKET_KEYS,
)
from app.security.jwt import AuthUser, PROJECT_ROLE_RANK
from app.security.project_membership import require_project_membership
from app.services import assets_query, project_scope

router = APIRouter(
    prefix="/api/projects/{project_id}/assets",
    tags=["assets"],
)

ASSET_ID_PATH_REGEX = r"^[0-9a-f]{64}$"

#: Maximum rows allowed in a single export response; larger matches -> 413.
EXPORT_ROW_CAP: int = 50_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def load_active_project_or_422(
    session: AsyncSession, project_id: uuid.UUID
) -> Project:
    """Reject legacy sentinel + archived projects with 422.

    RATIONALE (locked in revision): no canonical public helper exists in
    app.security.project_membership for the legacy/archived guard — that guard
    currently lives as `_load_project_or_404` in routers/easm.py. Cross-router
    `_`-import is an anti-pattern, so this router defines its own 10-line public
    helper. If a canonical guard lands later, migrate here.
    """
    proj = (
        await session.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if proj is None:
        raise HTTPException(status_code=404, detail="project_not_found")
    if proj.id == LEGACY_PROJECT_ID or proj.archived:
        raise HTTPException(
            status_code=422,
            detail="Assets are not available for archived or legacy projects.",
        )
    return proj


def _asset_row_id(bbot_event_type: str, canonical_target: str) -> str:
    """Alias of assets_query.asset_id_for for router-local readability."""
    return assets_query.asset_id_for(bbot_event_type, canonical_target)


async def _find_asset_by_id(
    session: AsyncSession,
    project_id: uuid.UUID,
    asset_id: str,
) -> tuple[str, str] | None:
    """Resolve asset_id → (bbot_event_type, canonical_target) for this project."""
    stmt = assets_query.build_assets_aggregation_select(project_id)
    rows = (await session.execute(stmt)).all()
    for row in rows:
        if _asset_row_id(row.bbot_event_type, row.canonical_target) == asset_id:
            return (row.bbot_event_type, row.canonical_target)
    return None


def _annotate_rows(
    raw_rows: list[Any],
    scope_rows: list,
    stale_cutoff: datetime | None,
) -> list[dict]:
    """Turn aggregation SELECT rows into dicts with asset_id + scope + stale populated."""
    annotated: list[dict] = []
    for row in raw_rows:
        scope = assets_query.compute_asset_scope(
            row.bbot_event_type, row.canonical_target, scope_rows
        )
        last_seen = row.last_seen
        stale = bool(stale_cutoff and last_seen and last_seen < stale_cutoff)
        modules = [m for m in (row.modules or []) if m is not None]
        annotated.append({
            "asset_id": _asset_row_id(row.bbot_event_type, row.canonical_target),
            "bbot_event_type": row.bbot_event_type,
            "canonical_target": row.canonical_target,
            "scope": scope,
            "first_seen": row.first_seen,
            "last_seen": row.last_seen,
            "scan_count": row.scan_count,
            "modules": modules,
            "stale": stale,
            "severity_max": row.severity_max,
        })
    return annotated


# ---------------------------------------------------------------------------
# Shared filter pipeline — consumed by list_assets + export_assets.
# ---------------------------------------------------------------------------


async def _collect_filtered_rows(
    *,
    session: AsyncSession,
    project_id: uuid.UUID,
    type: list[str] | None,
    scope: list[AssetScope] | None,
    stale: StaleFilter,
    module: list[str] | None,
    first_seen_from: datetime | None,
    first_seen_to: datetime | None,
    last_seen_from: datetime | None,
    last_seen_to: datetime | None,
    search: str | None,
    scan_id: uuid.UUID | None,
) -> list[dict]:
    """Run the aggregation + annotation + filter pipeline and return annotated row dicts.

    Callers: `list_assets` (list endpoint), `export_assets` (export endpoint).
    Sort is applied inside this helper (default `last_seen DESC`, None last) so
    callers get a stable order for pagination and export row stream.
    """
    # Pitfall 2: scope rows fetched ONCE per request.
    scope_rows = await project_scope.fetch_scope_rows_intel(session, project_id)
    stale_cutoff = await assets_query.load_stale_cutoff(session, project_id)

    stmt = assets_query.build_assets_aggregation_select(project_id)

    # SQL-side filters applied BEFORE aggregation where possible.
    if type:
        stmt = stmt.where(EASMFinding.bbot_event_type.in_(list(type)))
    if search:
        stmt = stmt.where(EASMFinding.canonical_target.ilike(f"%{search}%"))
    if scan_id is not None:
        stmt = stmt.where(EASMFinding.scan_id == scan_id)
    if module:
        stmt = stmt.where(EASMFinding.module.in_(list(module)))

    raw_rows = (await session.execute(stmt)).all()
    annotated = _annotate_rows(raw_rows, scope_rows, stale_cutoff)

    # Post-aggregation date-range filters (MIN/MAX are per-aggregated-row).
    if first_seen_from is not None:
        annotated = [r for r in annotated if r["first_seen"] and r["first_seen"] >= first_seen_from]
    if first_seen_to is not None:
        annotated = [r for r in annotated if r["first_seen"] and r["first_seen"] <= first_seen_to]
    if last_seen_from is not None:
        annotated = [r for r in annotated if r["last_seen"] and r["last_seen"] >= last_seen_from]
    if last_seen_to is not None:
        annotated = [r for r in annotated if r["last_seen"] and r["last_seen"] <= last_seen_to]

    # Python-side scope filter
    if scope:
        wanted = {s for s in scope}
        annotated = [r for r in annotated if r["scope"] in wanted]

    # Python-side stale filter
    if stale == StaleFilter.HIDE:
        annotated = [r for r in annotated if not r["stale"]]
    elif stale == StaleFilter.ONLY:
        annotated = [r for r in annotated if r["stale"]]

    # Default sort: last_seen DESC (None last)
    annotated.sort(
        key=lambda r: (r["last_seen"] is None, r["last_seen"]),
        reverse=True,
    )

    return annotated


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/assets — list
# ---------------------------------------------------------------------------


@router.get("", response_model=AssetListResponse, operation_id="listAssets")
async def list_assets(
    project_id: uuid.UUID,
    _member: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    session: AsyncSession = Depends(get_session),
    type: list[str] | None = Query(default=None, alias="type"),
    scope: list[AssetScope] | None = Query(default=None),
    stale: StaleFilter = Query(default=StaleFilter.SHOW),
    module: list[str] | None = Query(default=None),
    first_seen_from: datetime | None = Query(default=None),
    first_seen_to: datetime | None = Query(default=None),
    last_seen_from: datetime | None = Query(default=None),
    last_seen_to: datetime | None = Query(default=None),
    search: str | None = Query(default=None),
    scan_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AssetListResponse:
    """Paginated, filterable list of aggregated assets for the project."""
    await load_active_project_or_422(session, project_id)

    annotated = await _collect_filtered_rows(
        session=session,
        project_id=project_id,
        type=type,
        scope=scope,
        stale=stale,
        module=module,
        first_seen_from=first_seen_from,
        first_seen_to=first_seen_to,
        last_seen_from=last_seen_from,
        last_seen_to=last_seen_to,
        search=search,
        scan_id=scan_id,
    )

    total = len(annotated)
    page = annotated[offset : offset + limit]
    items = [AssetRow.model_validate(r) for r in page]

    return AssetListResponse(items=items, total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/assets/summary — 7-bucket counts
# ---------------------------------------------------------------------------


@router.get("/summary", response_model=AssetSummary, operation_id="getAssetsSummary")
async def assets_summary(
    project_id: uuid.UUID,
    _member: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    session: AsyncSession = Depends(get_session),
) -> AssetSummary:
    """Return per-bucket counts + stale counts for the dashboard summary cards."""
    await load_active_project_or_422(session, project_id)

    scope_rows = await project_scope.fetch_scope_rows_intel(session, project_id)
    stale_cutoff = await assets_query.load_stale_cutoff(session, project_id)

    stmt = assets_query.build_assets_aggregation_select(project_id)
    raw_rows = (await session.execute(stmt)).all()
    annotated = _annotate_rows(raw_rows, scope_rows, stale_cutoff)

    buckets = assets_query.summary_from_rows(annotated)
    # Ensure all 7 bucket keys present (summary_from_rows guarantees this;
    # belt-and-braces to honour the must_have truth).
    for k in SUMMARY_BUCKET_KEYS:
        buckets.setdefault(k, buckets.get(k))  # no-op for already-present keys

    return AssetSummary(buckets=buckets)


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/assets/export — CSV/JSON export
# ---------------------------------------------------------------------------
#
# Declared BEFORE the detail endpoint so FastAPI's declaration-order route
# matcher tries `/export` first; the asset_id pattern would not match "export"
# anyway (not 64 hex), but explicit ordering keeps behaviour obvious.


#: CSV column set exported for each asset row. Ten columns locked to the
#: annotated shape produced by `_collect_filtered_rows`.
_EXPORT_CSV_COLUMNS: list[str] = [
    "asset_id",
    "bbot_event_type",
    "canonical_target",
    "scope",
    "first_seen",
    "last_seen",
    "scan_count",
    "modules",
    "stale",
    "severity_max",
]


def _export_filename(project_id: uuid.UUID, fmt: AssetExportFormat) -> str:
    date_stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Project.slug does not exist on the model; use project_id stringified.
    return f"intellibird-assets-{project_id}-{date_stamp}.{fmt.value}"


def _csv_cell(row: dict, col: str) -> str:
    val = row.get(col)
    if col in ("first_seen", "last_seen"):
        return val.isoformat() if val else ""
    if col == "modules":
        return ";".join(val or [])
    if col == "stale":
        return "true" if val else "false"
    if val is None:
        return ""
    return str(val)


def _row_to_json_obj(row: dict) -> dict[str, Any]:
    return {
        "asset_id": row["asset_id"],
        "bbot_event_type": row["bbot_event_type"],
        "canonical_target": row["canonical_target"],
        "scope": str(row["scope"]) if row["scope"] is not None else None,
        "first_seen": row["first_seen"].isoformat() if row["first_seen"] else None,
        "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
        "scan_count": row["scan_count"],
        "modules": list(row["modules"] or []),
        "stale": bool(row["stale"]),
        "severity_max": row["severity_max"],
    }


@router.get("/export", operation_id="exportAssets")
async def export_assets(
    project_id: uuid.UUID,
    format: AssetExportFormat = Query(...),
    _member: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    session: AsyncSession = Depends(get_session),
    type: list[str] | None = Query(default=None, alias="type"),
    scope: list[AssetScope] | None = Query(default=None),
    stale: StaleFilter = Query(default=StaleFilter.SHOW),
    module: list[str] | None = Query(default=None),
    first_seen_from: datetime | None = Query(default=None),
    first_seen_to: datetime | None = Query(default=None),
    last_seen_from: datetime | None = Query(default=None),
    last_seen_to: datetime | None = Query(default=None),
    search: str | None = Query(default=None),
    scan_id: uuid.UUID | None = Query(default=None),
):
    """Export filtered asset rows as CSV or JSON (downloaded as attachment).

    Mirrors the list endpoint's filter parameter set. Returns 413 when the
    matched row count exceeds `EXPORT_ROW_CAP` so clients narrow scope rather
    than stream unbounded payloads.
    """
    await load_active_project_or_422(session, project_id)

    rows = await _collect_filtered_rows(
        session=session,
        project_id=project_id,
        type=type,
        scope=scope,
        stale=stale,
        module=module,
        first_seen_from=first_seen_from,
        first_seen_to=first_seen_to,
        last_seen_from=last_seen_from,
        last_seen_to=last_seen_to,
        search=search,
        scan_id=scan_id,
    )

    if len(rows) > EXPORT_ROW_CAP:
        raise HTTPException(
            status_code=413,
            detail={
                "matched": len(rows),
                "cap": EXPORT_ROW_CAP,
                "detail": "Too many assets — narrow filter before exporting.",
            },
        )

    filename = _export_filename(project_id, format)

    if format == AssetExportFormat.CSV:
        def row_iter():
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=_EXPORT_CSV_COLUMNS)
            writer.writeheader()
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
            for row in rows:
                writer.writerow({col: _csv_cell(row, col) for col in _EXPORT_CSV_COLUMNS})
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate(0)

        return StreamingResponse(
            row_iter(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # JSON: compact single-shot Response (array of row objects).
    body = _json.dumps([_row_to_json_obj(r) for r in rows])
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/assets/{asset_id} — detail
# ---------------------------------------------------------------------------


@router.get(
    "/{asset_id}",
    response_model=AssetDetail,
    operation_id="getAssetDetail",
)
async def asset_detail(
    project_id: uuid.UUID,
    asset_id: Annotated[str, Path(pattern=ASSET_ID_PATH_REGEX)],
    _member: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    session: AsyncSession = Depends(get_session),
) -> AssetDetail:
    """Return aggregated row + findings (drawer) + promoted events + note."""
    await load_active_project_or_422(session, project_id)

    scope_rows = await project_scope.fetch_scope_rows_intel(session, project_id)
    stale_cutoff = await assets_query.load_stale_cutoff(session, project_id)

    resolved = await _find_asset_by_id(session, project_id, asset_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="asset_not_found")
    bbot_event_type, canonical_target = resolved

    # Re-aggregate for just this (type, target) — reuse same SELECT then filter
    # in Python so we keep a single source of truth on aggregation shape.
    agg_stmt = assets_query.build_assets_aggregation_select(project_id).where(
        and_(
            EASMFinding.bbot_event_type == bbot_event_type,
            EASMFinding.canonical_target == canonical_target,
        )
    )
    agg_rows = (await session.execute(agg_stmt)).all()
    annotated = _annotate_rows(agg_rows, scope_rows, stale_cutoff)
    if not annotated:
        raise HTTPException(status_code=404, detail="asset_not_found")
    row = annotated[0]

    # Findings fan-out (drawer-only raw_bbot — Pitfall 1).
    finding_stmt = (
        select(EASMFinding, EASMScan.started_at)
        .join(EASMScan, EASMScan.id == EASMFinding.scan_id)
        .where(
            EASMFinding.project_id == project_id,
            EASMFinding.bbot_event_type == bbot_event_type,
            EASMFinding.canonical_target == canonical_target,
        )
        .order_by(EASMScan.started_at.desc())
    )
    finding_rows = (await session.execute(finding_stmt)).all()
    findings: list[AssetFinding] = []
    for f, started_at in finding_rows:
        findings.append(
            AssetFinding(
                id=f.id,
                scan_id=f.scan_id,
                scan_started_at=started_at,
                module=f.module,
                lifecycle_status=f.lifecycle_status,
                severity=f.severity,
                first_seen=f.first_seen,
                last_seen=f.last_seen,
                raw_bbot=f.raw_bbot if isinstance(f.raw_bbot, dict) else None,
            )
        )

    # Promoted events via content_hash (LOCKED — matches easm_promoter.py).
    content_hash_subq = (
        select(EASMFinding.content_hash)
        .where(
            EASMFinding.project_id == project_id,
            EASMFinding.bbot_event_type == bbot_event_type,
            EASMFinding.canonical_target == canonical_target,
        )
        .scalar_subquery()
    )
    promoted_stmt = (
        select(Event.id, Event.stix_type, Event.title, Event.observed_at)
        .where(
            Event.project_id == project_id,
            Event.easm_scan_id.isnot(None),
            Event.content_hash.in_(content_hash_subq),
        )
        .order_by(Event.observed_at.desc())
    )
    promoted_rows = (await session.execute(promoted_stmt)).all()
    promoted_events = [
        AssetPromotedEvent(
            id=r.id,
            stix_type=r.stix_type,
            title=r.title,
            observed_at=r.observed_at,
        )
        for r in promoted_rows
    ]

    # Note (optional).
    note_row = (
        await session.execute(
            select(AssetNote).where(
                AssetNote.project_id == project_id,
                AssetNote.bbot_event_type == bbot_event_type,
                AssetNote.canonical_target == canonical_target,
            )
        )
    ).scalar_one_or_none()
    note = AssetNoteRead.model_validate(note_row) if note_row is not None else None

    return AssetDetail(
        asset_id=row["asset_id"],
        bbot_event_type=row["bbot_event_type"],
        canonical_target=row["canonical_target"],
        scope=row["scope"],
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        scan_count=row["scan_count"],
        modules=row["modules"],
        stale=row["stale"],
        severity_max=row["severity_max"],
        findings=findings,
        promoted_events=promoted_events,
        note=note,
    )


# ---------------------------------------------------------------------------
# PATCH /api/projects/{project_id}/assets/{asset_id}/note — upsert note
# ---------------------------------------------------------------------------


@router.patch(
    "/{asset_id}/note",
    response_model=AssetNoteRead,
    operation_id="patchAssetNote",
)
async def patch_asset_note(
    project_id: uuid.UUID,
    asset_id: Annotated[str, Path(pattern=ASSET_ID_PATH_REGEX)],
    body: AssetNotePatch,
    user: AuthUser = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> AssetNoteRead:
    """Upsert the free-text note for a single asset.

    Authority matrix (CONTEXT §Authority matrix + UI-SPEC):
      * global Admin or Analyst → allowed (Admin also bypasses membership)
      * project rank ≥ Contributor → allowed
      * project Observer or global Viewer with no membership → 403
    """
    await load_active_project_or_422(session, project_id)

    # Authority check — explicit. require_auth (not require_project_membership)
    # is used so the helper below can distinguish Observer (403) from missing
    # membership (also 403) with matching copy to the easm patch_finding path.
    contributor_rank = PROJECT_ROLE_RANK["Contributor"]
    if user.role in {"Admin", "Analyst"}:
        pass
    else:
        rank = user.project_memberships.get(str(project_id), 0)
        if rank < contributor_rank:
            raise HTTPException(
                status_code=403,
                detail="Edit note requires Contributor or higher.",
            )

    match = await _find_asset_by_id(session, project_id, asset_id)
    if match is None:
        raise HTTPException(status_code=404, detail="asset_not_found")
    bbot_event_type, canonical_target = match

    now = datetime.now(timezone.utc)
    stmt = (
        pg_insert(AssetNote)
        .values(
            id=uuid.uuid4(),
            project_id=project_id,
            bbot_event_type=bbot_event_type,
            canonical_target=canonical_target,
            note=body.note,
            updated_by=user.id,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["project_id", "bbot_event_type", "canonical_target"],
            set_={
                "note": body.note,
                "updated_by": user.id,
                "updated_at": now,
            },
        )
        .returning(AssetNote)
    )
    result = await session.execute(stmt)
    await session.commit()
    row = result.scalar_one()
    return AssetNoteRead.model_validate(row, from_attributes=True)
