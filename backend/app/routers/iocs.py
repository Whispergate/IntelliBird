"""IOC read-only API — Phase 22 / IOC-03, IOC-06, IOC-08.

Endpoints:
  GET /api/iocs              list (paginated, filtered)
  GET /api/iocs/{id}         detail
  GET /api/iocs/{id}/events  linked events via ioc_event_links

Write paths (POST/PATCH/DELETE/whitelist/bulk-import) live in plans 22-04 / 22-05.
The companion event-side endpoint `GET /api/events/{event_id}/iocs` lives in
`app.routers.events` (alongside the existing event handlers) — both surfaces go
through `app.services.ioc_query.build_ioc_scope_predicate` so cross-project
leakage is structurally impossible regardless of which direction the caller
pivots from.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.database import get_session
from app.models.events import Event
from app.models.iocs import IOC, IOC_TYPES, IOCEventLink
from app.models.projects import ProjectRole
from app.schemas.iocs import IOCPatch, IOCRead
from app.security.jwt import PROJECT_ROLE_RANK
from app.services.ioc_query import apply_default_filters, build_ioc_scope_predicate
from app.services.iocs import clone_global_to_project_whitelisted

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/iocs", tags=["iocs"])


def _user_from_request(request: Request) -> Any:
    """Return request.state.user (AuthUser populated by AuthMiddleware).

    Returns None when AUTH_ENABLED=false AND the middleware has not injected
    the dev-stub admin (defensive — middleware always injects when disabled).
    The scope predicate handles None as "global rows only" via empty
    membership fallback.
    """
    return getattr(request.state, "user", None)


@router.get("", response_model=list[IOCRead])
async def list_iocs(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    type: list[str] | None = Query(default=None, description="Filter by IOC type (multi)."),
    status_: str | None = Query(
        default=None,
        alias="status",
        description="Filter by status (active/expired/whitelisted). Default: hide expired.",
    ),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    age_days: int | None = Query(
        default=None, ge=1,
        description="Only IOCs whose last_seen is within the last N days.",
    ),
    q: str | None = Query(
        default=None, max_length=512,
        description="Substring search over value / normalized_value.",
    ),
    project_id: uuid.UUID | None = Query(
        default=None,
        description="Restrict to a single project (combined with global rows).",
    ),
    include_expired: bool = Query(
        default=False,
        description="When true, surface status='expired' rows (IOC-05 soft-expire).",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(
        default=None,
        description="Opaque cursor (currently unused — keyset pagination wired in 22-04).",
    ),
) -> list[IOCRead]:
    """List IOCs scoped per `build_ioc_scope_predicate`.

    Cursor pagination scaffold is in place but the keyset cursor is intentionally
    inert in this plan — when 22-04 ships writes / re-sighting the upsert path
    bumps `last_seen`, and the cursor encoding will mirror the events keyset
    `(last_seen DESC, id DESC)` shape. For now the route caps results via `limit`.
    """
    user = _user_from_request(request)

    # Validate type filter values up-front so a typo returns 422 instead of an empty result.
    if type:
        unknown = [t for t in type if t not in IOC_TYPES]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown IOC type(s): {unknown}. Must be one or more of {list(IOC_TYPES)}.",
            )

    stmt = select(IOC).where(build_ioc_scope_predicate(user, project_filter=project_id))

    if status_ is not None:
        # Caller asked for a specific status — honour it verbatim, do NOT apply
        # the default-hide-expired filter on top.
        stmt = stmt.where(IOC.status == status_)
    else:
        stmt = apply_default_filters(stmt, include_expired=include_expired)

    if type:
        stmt = stmt.where(IOC.type.in_(type))
    if min_confidence is not None:
        stmt = stmt.where(IOC.confidence >= min_confidence)
    if age_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=age_days)
        stmt = stmt.where(IOC.last_seen >= cutoff)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(IOC.value).like(like),
                func.lower(IOC.normalized_value).like(like),
            )
        )

    stmt = stmt.order_by(desc(IOC.last_seen), desc(IOC.id)).limit(limit)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    log.info(
        "iocs_listed",
        count=len(rows),
        project_id=str(project_id) if project_id else None,
        types=type,
        status=status_,
        include_expired=include_expired,
    )
    return rows


@router.get("/{ioc_id}", response_model=IOCRead)
async def get_ioc(
    ioc_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> IOCRead:
    """Single IOC detail. 404 when invisible to the caller under the scope predicate.

    Returning 404 (not 403) for invisible rows is intentional — an attacker
    iterating UUIDs must not be able to distinguish "exists but not yours"
    from "does not exist".
    """
    user = _user_from_request(request)
    stmt = select(IOC).where(IOC.id == ioc_id, build_ioc_scope_predicate(user))
    row = (await db.execute(stmt)).scalars().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="ioc_not_found")
    return row


@router.get("/{ioc_id}/events")
async def get_ioc_events(
    ioc_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=25, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Linked events for an IOC, sorted by `events.observed_at` DESC.

    Note on field naming: the plan/spec mentions `published_at`; the Event model
    in this repo uses `observed_at` (events are time-partitioned by observed_at
    via the TimescaleDB hypertable). We sort by `observed_at` and surface it
    under the same key in the response body — frontends consuming Plan 22-06's
    IOC drawer §Surface 4 should treat `observed_at` as the canonical display
    timestamp.

    Returns 404 when the IOC itself is invisible to the caller.
    """
    user = _user_from_request(request)

    # Visibility gate on the IOC itself — same scope predicate as GET /api/iocs/{id}.
    visible_stmt = select(IOC.id).where(
        IOC.id == ioc_id, build_ioc_scope_predicate(user)
    )
    if (await db.execute(visible_stmt)).scalars().first() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="ioc_not_found")

    link_stmt = (
        select(Event)
        .join(IOCEventLink, IOCEventLink.event_id == Event.id)
        .where(IOCEventLink.ioc_id == ioc_id)
        .order_by(desc(Event.observed_at))
        .limit(limit)
    )
    rows = list((await db.execute(link_stmt)).scalars().all())
    return [
        {
            "id": str(e.id),
            "title": e.title,
            "observed_at": e.observed_at,
            "stix_type": e.stix_type,
            "visibility": e.visibility,
            "source_id": str(e.source_id) if e.source_id else None,
        }
        for e in rows
    ]


# ---------------------------------------------------------------------------
# Plan 22-04 write endpoints — whitelist (with clone-on-whitelist) + PATCH +
# DELETE. The /{ioc_id} routes can't use `require_project_membership` (which
# resolves the project from a `project_id` path param); membership is checked
# manually below against `AuthUser.project_memberships` (JWT pm claim) per the
# pattern documented in the Plan 22-03 SUMMARY §AuthUser reference.
# ---------------------------------------------------------------------------
from datetime import datetime as _dt_now, timezone as _tz_now  # noqa: E402
from sqlalchemy import delete as _sa_delete, select as _sa_select  # noqa: E402


def _is_admin(user: Any) -> bool:
    """Match `app/middleware/auth.py:200` — `user.role == "Admin"`."""
    return getattr(user, "role", None) == "Admin"


def _has_project_role(user: Any, project_id: uuid.UUID, min_role: ProjectRole) -> bool:
    """Mirror security.project_membership.require_project_membership step 2 (JWT
    cached path). Admin bypass returns True. Returns False when the JWT pm
    claim has no entry for ``project_id`` or the cached rank is below
    ``min_role``.

    No DB fallback here — the JWT pm claim is the source of truth on the
    request path (see Plan 22-03 SUMMARY §"Membership lookup via JWT claim,
    not DB"). If a Lead's JWT was minted before they were granted membership,
    they need to refresh — same behaviour as the rest of the app.
    """
    if _is_admin(user):
        return True
    pm: dict[str, int] = getattr(user, "project_memberships", None) or {}
    cached = pm.get(str(project_id))
    if cached is None:
        return False
    min_rank = PROJECT_ROLE_RANK[min_role.value]
    return cached >= min_rank


async def _fetch_visible_ioc(db: AsyncSession, user: Any, ioc_id: uuid.UUID) -> IOC:
    """Load the IOC under the scope predicate — 404 when not visible."""
    stmt = _sa_select(IOC).where(IOC.id == ioc_id, build_ioc_scope_predicate(user))
    row = (await db.execute(stmt)).scalars().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="ioc_not_found")
    return row


@router.post("/{ioc_id}/whitelist", response_model=IOCRead)
async def whitelist_ioc(
    ioc_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    project_id: uuid.UUID | None = Query(
        default=None,
        description=(
            "Required when whitelisting a global row as a non-admin Lead — "
            "the project to clone the row into (clone-on-whitelist)."
        ),
    ),
) -> IOC:
    """Per-row whitelist toggle — IOC-04.

    Three role/scope paths (per CONTEXT.md §"Whitelist scope per-row"):

      1. Per-project IOC + Admin or Lead-on-that-project → in-place flip
      2. Global IOC + Admin → in-place flip (everyone sees it whitelisted)
      3. Global IOC + non-admin Lead → clone-on-whitelist into the Lead's
         project; the global row is NOT modified
    """
    user = _user_from_request(request)
    ioc = await _fetch_visible_ioc(db, user, ioc_id)
    is_admin = _is_admin(user)

    # Path 2: global row + admin → whitelist in place
    if ioc.project_id is None and is_admin:
        ioc.status = "whitelisted"
        ioc.updated_at = _dt_now.now(_tz_now.utc)
        await db.commit()
        await db.refresh(ioc)
        log.info("ioc_whitelisted_in_place ioc_id=%s scope=global", str(ioc.id))
        return ioc

    # Path 3: global row + non-admin Lead → clone into target project
    if ioc.project_id is None and not is_admin:
        if project_id is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=(
                    "project_id query param required when a non-admin Lead "
                    "whitelists a global row (clone-on-whitelist)"
                ),
            )
        if not _has_project_role(user, project_id, ProjectRole.Lead):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="requires Lead on target project",
            )
        user_sub = str(getattr(user, "id", "")) or None
        new_id = await clone_global_to_project_whitelisted(
            db, ioc, project_id, user_sub
        )
        log.info(
            "ioc_cloned_for_whitelist global_ioc_id=%s new_ioc_id=%s project_id=%s",
            str(ioc.id), str(new_id), str(project_id),
        )
        return await _fetch_visible_ioc(db, user, new_id)

    # Path 1: per-project row → require Lead on its project (Admin auto-passes)
    if not _has_project_role(user, ioc.project_id, ProjectRole.Lead):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="requires Lead on IOC project",
        )
    ioc.status = "whitelisted"
    ioc.updated_at = _dt_now.now(_tz_now.utc)
    await db.commit()
    await db.refresh(ioc)
    log.info(
        "ioc_whitelisted_in_place ioc_id=%s scope=project project_id=%s",
        str(ioc.id), str(ioc.project_id),
    )
    return ioc


@router.delete("/{ioc_id}/whitelist", response_model=IOCRead)
async def unwhitelist_ioc(
    ioc_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> IOC:
    """Reverse a whitelist — flips status back to 'active'.

    For cloned shadow rows this just flips the shadow back; no merge with the
    global row is attempted (the two are independent per CONTEXT.md).
    """
    user = _user_from_request(request)
    ioc = await _fetch_visible_ioc(db, user, ioc_id)
    if ioc.project_id is None:
        if not _is_admin(user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="global_ioc_admin_only")
    else:
        if not _has_project_role(user, ioc.project_id, ProjectRole.Lead):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, detail="requires Lead on IOC project"
            )
    ioc.status = "active"
    ioc.updated_at = _dt_now.now(_tz_now.utc)
    await db.commit()
    await db.refresh(ioc)
    return ioc


@router.patch("/{ioc_id}", response_model=IOCRead)
async def patch_ioc(
    ioc_id: uuid.UUID,
    body: IOCPatch,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> IOC:
    """Lead+ updates `confidence` + `ttl_days` only (UI Surface 4e).

    Other fields (type, value, status) are intentionally NOT mutable here —
    status flips go through the whitelist endpoints, and immutable identity
    fields force re-import for correctness/audit.
    """
    user = _user_from_request(request)
    ioc = await _fetch_visible_ioc(db, user, ioc_id)
    if ioc.project_id is None:
        if not _is_admin(user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="global_ioc_admin_only")
    else:
        if not _has_project_role(user, ioc.project_id, ProjectRole.Lead):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, detail="requires Lead on IOC project"
            )

    if body.confidence is not None:
        ioc.confidence = body.confidence
    if body.ttl_days is not None:
        ioc.ttl_days = body.ttl_days
    ioc.updated_at = _dt_now.now(_tz_now.utc)
    await db.commit()
    await db.refresh(ioc)
    return ioc


@router.delete("/{ioc_id}", status_code=204)
async def delete_ioc(
    ioc_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Admin-only hard delete — ioc_event_links cascade via FK (UI Surface 7).

    Decision: hard delete (NOT soft-delete) — whitelist already provides the
    soft-suppression semantic; a separate "deleted" status would muddy the
    state machine. Audit lives in the operator's git/log retention rather
    than tombstone rows.
    """
    user = _user_from_request(request)
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="admin_only")
    ioc = await _fetch_visible_ioc(db, user, ioc_id)
    await db.execute(_sa_delete(IOC).where(IOC.id == ioc.id))
    await db.commit()
    log.info("ioc_deleted ioc_id=%s by_user=%s", str(ioc.id), getattr(user, "id", None))
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Plan 22-05 — POST /api/iocs/bulk-import (CSV / JSON / STIX 2.1)
#
# Two-phase pattern (CONTEXT.md §"Bulk import + STIX mapping"):
#   * ?dry_run=true → IOCBulkImportDryRun {would_insert, would_update,
#     would_skip, unmapped_sdo_count, errors[:50]}.  No writes.
#   * No dry_run    → 202 + {job_id, rows_accepted}.  Payload staged in
#     Redis under `ioc:import:{job_id}` (TTL 600s); the bulk_import_iocs
#     Dramatiq actor on `ingest` queue consumes it.
#
# Critical fixes from revision (must stay enforced here):
#   * Dry-run dedup uses `build_ioc_scope_predicate(user, project_filter=...)`
#     so a Lead can't enumerate cross-project IOCs by counting `would_update`
#     hits (revision checker warning #9 — same shape as PROD-01 leakage).
#   * Per-row `project_id` validated against the route's project_id for
#     non-admin uploads (revision checker warning #4) — admin uploads are
#     unrestricted so they can stage global rows in one CSV.
# ---------------------------------------------------------------------------
import json as _json  # noqa: E402
from app.services.ioc_import import (  # noqa: E402
    parse_csv_rows as _parse_csv_rows,
    parse_json_rows as _parse_json_rows,
    parse_stix_bundle as _parse_stix_bundle,
    IOCImportTooLarge as _IOCImportTooLarge,
)
from app.services.iocs import normalise as _normalise_value  # noqa: E402
from app.services.redis_client import get_redis as _get_redis  # noqa: E402
from app.schemas.iocs import (  # noqa: E402
    IOCImportRow as _IOCImportRow,
    IOCBulkImportDryRun as _IOCBulkImportDryRun,
    IOCBulkImportEnqueued as _IOCBulkImportEnqueued,
)


_BULK_IMPORT_ROW_CAP = 10_000


@router.post("/bulk-import")
async def bulk_import(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    dry_run: bool = Query(default=False),
    project_id: uuid.UUID | None = Query(
        default=None,
        description="Destination project. Omit (admin only) for global rows.",
    ),
    format: str | None = Query(
        default=None,
        description="Override the format detected from Content-Type. csv|json|stix.",
    ),
):
    """Upload IOCs in bulk via CSV / JSON / STIX 2.1 — IOC-02.

    Auth: Lead+ on the destination project; Admin required for global rows
    (project_id=None). Format is detected from Content-Type unless `?format=`
    overrides.
    """
    user = _user_from_request(request)
    is_admin = _is_admin(user)

    # 1. Auth — global is admin-only; per-project requires Lead+.
    if project_id is None and not is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="global_import_admin_only"
        )
    if project_id is not None and not is_admin:
        if not _has_project_role(user, project_id, ProjectRole.Lead):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, detail="requires Lead on target project"
            )

    # 2. Format detection — Content-Type → fmt; ?format= override wins.
    ct = (request.headers.get("content-type") or "").lower()
    body = await request.body()
    if format:
        fmt = format.lower()
    elif "csv" in ct:
        fmt = "csv"
    elif "stix" in ct:
        fmt = "stix"
    elif "json" in ct:
        fmt = "json"
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="unrecognised_format"
        )
    if fmt not in ("csv", "json", "stix"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"unsupported_format: {fmt}"
        )

    # 3. Parse rows + collect per-row errors.
    rows: list[_IOCImportRow] = []
    errors: list[dict[str, Any]] = []
    unmapped_sdo_count = 0
    try:
        if fmt == "csv":
            for r in _parse_csv_rows(body):
                if r.error:
                    errors.append(
                        {"line": r.line, "value": r.value, "error": r.error}
                    )
                else:
                    rows.append(r)
        elif fmt == "json":
            for r in _parse_json_rows(body):
                if r.error:
                    errors.append(
                        {"line": r.line, "value": r.value, "error": r.error}
                    )
                else:
                    rows.append(r)
        else:  # stix
            try:
                bundle = _json.loads(body.decode("utf-8-sig"))
            except (UnicodeDecodeError, _json.JSONDecodeError) as exc:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail=f"parse_failed: {exc}",
                )
            if not isinstance(bundle, dict):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail="parse_failed: stix bundle must be an object",
                )
            for ioc_type, raw_value in _parse_stix_bundle(bundle):
                rows.append(_IOCImportRow(type=ioc_type, value=raw_value))
            unmapped_sdo_count = sum(
                1 for o in (bundle.get("objects") or [])
                if isinstance(o, dict)
                and o.get("type") not in ("indicator", "observed-data")
            )
    except _IOCImportTooLarge:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="row_cap_exceeded"
        )
    except (ValueError, _json.JSONDecodeError) as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"parse_failed: {exc}"
        )

    if len(rows) > _BULK_IMPORT_ROW_CAP:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="row_cap_exceeded"
        )

    # 4. Per-row project_id validation (revision checker fix #4).
    #    Non-admin uploads can't smuggle rows into other projects via the
    #    optional `project_id` CSV column; mismatches → 422.
    if not is_admin:
        for r in rows:
            if r.project_id is not None and r.project_id != project_id:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"row_project_id_mismatch: row.project_id={r.project_id} "
                        f"differs from route project_id={project_id} "
                        f"(line={r.line})"
                    ),
                )

    # 5. Dry-run dedup — SCOPED via build_ioc_scope_predicate so a Lead
    #    can't probe cross-project IOC presence by reading would_update
    #    counts (revision checker fix #9 — mirrors PROD-01 leakage shape).
    keys = [
        (project_id, r.type, _normalise_value(r.type, r.value)) for r in rows
    ]
    existing: set[tuple] = set()
    if keys:
        types = {k[1] for k in keys}
        norms = {k[2] for k in keys if k[2]}
        if norms:
            stmt = (
                select(IOC.project_id, IOC.type, IOC.normalized_value)
                .where(build_ioc_scope_predicate(user, project_filter=project_id))
                .where(IOC.type.in_(types))
                .where(IOC.normalized_value.in_(norms))
            )
            for pid, t, nv in (await db.execute(stmt)).all():
                # Only count as a dedup hit when the existing row is in the
                # SAME scope the import is targeting — a global row already
                # present must not show up as 'would_update' for a per-project
                # import (and vice-versa).
                if pid == project_id:
                    existing.add((pid, t, nv))

    would_update = sum(1 for k in keys if k in existing)
    would_insert = len(keys) - would_update
    would_skip = len(errors)

    if dry_run:
        return _IOCBulkImportDryRun(
            would_insert=would_insert,
            would_update=would_update,
            would_skip=would_skip,
            unmapped_sdo_count=unmapped_sdo_count,
            errors=errors[:50],
        )

    # 6. Real run — stage payload in Redis + enqueue Dramatiq actor.
    from app.workers.iocs import bulk_import_iocs as _bulk_import_iocs  # noqa: PLC0415

    job_id = str(uuid.uuid4())
    payload_key = f"ioc:import:{job_id}"
    redis = await _get_redis()
    await redis.set(
        payload_key,
        _json.dumps([row.model_dump(mode="json") for row in rows]),
        ex=600,
    )
    await redis.set(
        f"job:{job_id}:status",
        _json.dumps({"status": "queued", "total": len(rows), "processed": 0}),
        ex=3600,
    )
    user_sub = str(getattr(user, "id", "")) or "unknown"
    _bulk_import_iocs.send(
        job_id,
        payload_key,
        str(project_id) if project_id else None,
        user_sub,
        fmt,
    )
    log.info(
        "ioc_bulk_import_enqueued",
        job_id=job_id,
        rows_accepted=len(rows),
        format=fmt,
        project_id=str(project_id) if project_id else None,
    )
    return _IOCBulkImportEnqueued(job_id=job_id, rows_accepted=len(rows))
