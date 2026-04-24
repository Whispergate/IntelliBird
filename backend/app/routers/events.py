"""GET /api/events, GET /api/events/{id} — FIL-01, FIL-02."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.database import get_session
from app.models.events import Event
from app.models.markings import TlpMarking
from app.models.sources import Source
from app.models.tags import AttackTechniqueTag
from app.schemas.events import (
    EventDetail,
    EventItem,
    EventListResponse,
)
from app.services.events_query import (
    CursorError,
    EventsQueryParams,
    apply_cursor,
    apply_fts_cursor,
    build_events_query,
    build_fts_query,
    decode_cursor,
    decode_fts_cursor,
    encode_cursor,
    encode_fts_cursor,
)
from app.security.project_membership import enforce_project_query_scope
from app.services.project_scope import (
    build_scope_predicate,
    fetch_bound_sources,
    fetch_scope_rows_intel,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/events", tags=["events"])

FeedType = Literal["rss", "taxii", "nvd"]
TlpName = Literal["clear", "green", "amber", "amber+strict", "red"]


async def _hydrate_item(event: Event, db: AsyncSession) -> EventItem:
    """Populate source_name/source_type, resolve TLP name, collect attack_techniques."""
    source_name: str | None = None
    source_type: str | None = None
    if event.source_id is not None:
        row = (
            await db.execute(
                select(Source.name, Source.feed_type).where(Source.id == event.source_id)
            )
        ).one_or_none()
        if row is not None:
            source_name, source_type = row[0], row[1]

    tlp_name: str | None = None
    if event.tlp_marking_id is not None:
        row = (
            await db.execute(
                select(TlpMarking.name).where(TlpMarking.id == event.tlp_marking_id)
            )
        ).one_or_none()
        if row is not None:
            tlp_name = row[0]

    tech_rows = (
        await db.execute(
            select(AttackTechniqueTag.technique_id).where(
                AttackTechniqueTag.event_id == event.id
            )
        )
    ).all()
    attack_techniques = [r[0] for r in tech_rows]

    return EventItem(
        id=event.id,
        observed_at=event.observed_at,
        fetched_at=event.fetched_at,
        source_id=event.source_id,
        source_name=source_name,
        source_type=source_type,  # type: ignore[arg-type]
        stix_id=event.stix_id,
        stix_type=event.stix_type,
        title=event.title,
        description=event.description,
        tlp=tlp_name,  # type: ignore[arg-type]
        tags=(event.tags or []),
        attack_techniques=attack_techniques,
        archived=event.archived,
        visibility=event.visibility,  # type: ignore[arg-type]
        geo_lat=event.geo_lat,
        geo_lon=event.geo_lon,
    )


@router.get("", response_model=EventListResponse)
async def list_events(
    request: Request,
    source: list[uuid.UUID] | None = Query(default=None),
    source_type: list[FeedType] | None = Query(default=None),
    observed_from: datetime | None = Query(default=None),
    observed_to: datetime | None = Query(default=None),
    tlp: list[TlpName] | None = Query(default=None),
    attack_technique: list[str] | None = Query(default=None),
    tag: list[str] | None = Query(default=None),
    free_text: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    has_geo: bool = Query(default=False),
    tag_mode: Literal["any", "all"] = Query(default="all"),
    include_total: bool = Query(default=False),
    cursor: str | None = Query(default=None),
    # Cap raised from 200 → 1000 so dashboard KPI widgets (ActorInfra,
    # FreshExploits, ToolingChatter) can fetch 24h windows of up to 1000
    # events for sparkline bucketing. Below-200 list views ignore.
    limit: int = Query(default=50, ge=1, le=1000),
    project_id: uuid.UUID | None = Query(default=None),
    include_bbot: bool = Query(
        default=False,
        description=(
            "Include BBOT-promoted events in results. "
            "Default (false) excludes events where easm_scan_id IS NOT NULL "
            "(H-4 feed contamination prevention). Set true to show BBOT provenance events."
        ),
    ),
    include_brand_match: bool = Query(
        default=False,
        description=(
            "Include brand-monitor (Phase 12) events in results. "
            "Default (false) excludes events tagged 'brand-match' so the main "
            "events feed is not polluted by brand alerts. Set true to show them."
        ),
    ),
    db: AsyncSession = Depends(get_session),
) -> EventListResponse:
    # AUTH-02 / C-2: dashboard_roles sourced from JWT claim (request.state.user),
    # populated by AuthMiddleware. Dashboard role header removed (plan 09-05).
    # When AUTH_ENABLED=false, request.state.user is unset → dashboard_roles=None → no filter.
    # PROD-03: filtering role comes from dependency injection of JWT claim; do not inspect X-Dashboard-Role header.
    user = getattr(request.state, "user", None)
    dashboard_roles: list[str] | None = list(user.dashboard_roles) if user is not None else None

    # PROD-01 GAP-1: intersect JWT project_memberships with the row filter.
    # Non-admin callers without project_id previously saw all projects' events
    # because build_events_query skipped the scope predicate. Helper returns:
    #   - None for admins / anonymous (AUTH_ENABLED=false) → unrestricted
    #   - None when project_id is provided AND caller is a member → unchanged
    #   - 403 when caller has no memberships or is not a member of project_id
    #   - list[UUID] when multi-project caller omitted project_id → reject
    allowed_project_ids = enforce_project_query_scope(user, project_id)
    if allowed_project_ids is not None and project_id is None:
        raise HTTPException(
            status_code=400,
            detail="project_id query parameter required for non-admin callers",
        )

    # Phase 10 / PRJ-03: pre-compute scope predicate + bound sources when project-scoped.
    # build_events_query + build_fts_query stay sync — routers fetch the DB-dependent
    # pieces up-front and pass them in as kwargs.
    scope_predicate = None
    bound_sources: list[uuid.UUID] | None = None
    if project_id is not None:
        scope_rows = await fetch_scope_rows_intel(db, project_id)
        scope_predicate = build_scope_predicate(scope_rows)
        bound_sources = await fetch_bound_sources(db, project_id)

    if free_text is not None:
        q = free_text.strip()
        if not q:
            raise HTTPException(
                status_code=400, detail="free_text query cannot be empty"
            )

        # FTS path (FIL-05) — rank-ordered, triple-key cursor
        params = EventsQueryParams(
            source=source,
            source_type=source_type,
            observed_from=observed_from,
            observed_to=observed_to,
            tlp=tlp,
            attack_technique=attack_technique,
            tag=tag,
            include_archived=include_archived,
            has_geo=has_geo,
            tag_mode=tag_mode,
        )
        fts_stmt = build_fts_query(
            params, dashboard_roles, q,
            project_id=project_id,
            scope_predicate=scope_predicate,
            bound_sources=bound_sources,
        )
        # H-4 feed contamination prevention (Phase 11): exclude BBOT-promoted events
        # by default. BBOT provenance is signalled by easm_scan_id IS NOT NULL.
        # (events table has no source_type column — easm_scan_id is the sole indicator.)
        if not include_bbot:
            fts_stmt = fts_stmt.where(Event.easm_scan_id == None)  # noqa: E711

        # Phase 12 / BRP-04: exclude brand-monitor events unless explicitly
        # requested. Brand events are tagged 'brand-match' by brand_synth
        # (no source_type column exists on events; tag is the canonical marker).
        if not include_brand_match:
            fts_stmt = fts_stmt.where(
                ~func.coalesce(Event.tags, sa.cast(sa.literal("{}"), ARRAY(sa.Text)))
                .op("@>")(sa.cast(["brand-match"], ARRAY(sa.Text)))
            )

        if cursor:
            try:
                c_rank, c_ts, c_id = decode_fts_cursor(cursor)
            except CursorError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            fts_stmt = apply_fts_cursor(fts_stmt, q, c_rank, c_ts, c_id)

        fts_page = fts_stmt.limit(limit + 1)
        rows_raw = (await db.execute(fts_page)).all()  # list of (Event, rank) Row objects

        next_cursor: str | None = None
        if len(rows_raw) > limit:
            last_event, last_rank = rows_raw[limit - 1][0], float(rows_raw[limit - 1][1])
            next_cursor = encode_fts_cursor(
                last_rank, last_event.observed_at, last_event.id
            )
            rows_raw = rows_raw[:limit]

        total: int | None = None
        if include_total:
            _fts_count_base = build_fts_query(
                params, dashboard_roles, q,
                project_id=project_id,
                scope_predicate=scope_predicate,
                bound_sources=bound_sources,
            )
            if not include_bbot:
                _fts_count_base = _fts_count_base.where(Event.easm_scan_id == None)  # noqa: E711
            if not include_brand_match:
                _fts_count_base = _fts_count_base.where(
                    ~func.coalesce(Event.tags, sa.cast(sa.literal("{}"), ARRAY(sa.Text)))
                    .op("@>")(sa.cast(["brand-match"], ARRAY(sa.Text)))
                )
            count_stmt = select(func.count()).select_from(
                _fts_count_base.subquery()
            )
            total = int((await db.execute(count_stmt)).scalar_one())

        items = [await _hydrate_item(r[0], db) for r in rows_raw]
        log.info(
            "events_fts_queried",
            q=q,
            count=len(items),
            dashboard_roles=dashboard_roles,
            has_cursor=bool(cursor),
        )
        return EventListResponse(items=items, next_cursor=next_cursor, total=total)

    # Standard non-FTS path (keyset cursor on observed_at, id)
    params = EventsQueryParams(
        source=source,
        source_type=source_type,
        observed_from=observed_from,
        observed_to=observed_to,
        tlp=tlp,
        attack_technique=attack_technique,
        tag=tag,
        include_archived=include_archived,
        has_geo=has_geo,
        tag_mode=tag_mode,
    )

    stmt = build_events_query(
        params, dashboard_roles,
        project_id=project_id,
        scope_predicate=scope_predicate,
        bound_sources=bound_sources,
    )
    # H-4 feed contamination prevention (Phase 11): exclude BBOT-promoted events
    # by default. BBOT provenance is signalled by easm_scan_id IS NOT NULL.
    # (events table has no source_type column — easm_scan_id is the sole indicator.)
    if not include_bbot:
        stmt = stmt.where(Event.easm_scan_id == None)  # noqa: E711

    # Phase 12 / BRP-04: exclude brand-monitor events unless requested.
    if not include_brand_match:
        stmt = stmt.where(
            ~func.coalesce(Event.tags, sa.cast(sa.literal("{}"), ARRAY(sa.Text)))
            .op("@>")(sa.cast(["brand-match"], ARRAY(sa.Text)))
        )

    if cursor:
        try:
            cursor_ts, cursor_id = decode_cursor(cursor)
        except CursorError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        stmt = apply_cursor(stmt, cursor_ts, cursor_id)

    stmt_page = stmt.limit(limit + 1)
    rows = (await db.execute(stmt_page)).scalars().all()

    next_cursor_std: str | None = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor_std = encode_cursor(last.observed_at, last.id)
        rows = rows[:limit]

    total_std: int | None = None
    if include_total:
        # Total uses the FILTER-only stmt (no cursor, no limit) to avoid
        # counting only rows after the cursor position.
        _count_base = build_events_query(
            params, dashboard_roles,
            project_id=project_id,
            scope_predicate=scope_predicate,
            bound_sources=bound_sources,
        )
        if not include_bbot:
            _count_base = _count_base.where(Event.easm_scan_id == None)  # noqa: E711
        if not include_brand_match:
            _count_base = _count_base.where(
                ~func.coalesce(Event.tags, sa.cast(sa.literal("{}"), ARRAY(sa.Text)))
                .op("@>")(sa.cast(["brand-match"], ARRAY(sa.Text)))
            )
        count_stmt = select(func.count()).select_from(_count_base.subquery())
        total_std = int((await db.execute(count_stmt)).scalar_one())

    items = [await _hydrate_item(r, db) for r in rows]

    log.info(
        "events_listed",
        count=len(items),
        filters_applied=sum(
            1
            for v in [source, source_type, observed_from, observed_to, tlp, attack_technique, tag]
            if v
        ),
        dashboard_roles=dashboard_roles,
        has_cursor=bool(cursor),
        include_total=include_total,
    )
    return EventListResponse(items=items, next_cursor=next_cursor_std, total=total_std)


@router.get("/{event_id}", response_model=EventDetail)
async def get_event(
    event_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> EventDetail:
    # AUTH-02 / C-2: dashboard_roles sourced from JWT claim (request.state.user),
    # populated by AuthMiddleware. Dashboard role header removed (plan 09-05).
    user = getattr(request.state, "user", None)
    dashboard_roles: list[str] | None = list(user.dashboard_roles) if user is not None else None

    # Composite-PK aware lookup ( from 04-RESEARCH.md — NOT session.get)
    row = (
        await db.execute(select(Event).where(Event.id == event_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="event not found")

    # Visibility gate — return 404 to avoid information disclosure
    if dashboard_roles:
        if "red" not in dashboard_roles and row.visibility == "red_only":
            raise HTTPException(status_code=404, detail="event not found")
        if "blue" not in dashboard_roles and row.visibility == "blue_only":
            raise HTTPException(status_code=404, detail="event not found")

    item = await _hydrate_item(row, db)
    return EventDetail(**item.model_dump(), raw_stix=row.raw_stix)
