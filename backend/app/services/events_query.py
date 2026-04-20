"""Events list query builder — FIL-01, FIL-02.

Pure query construction. No DB execution here — routers pass the returned
Select to session.execute.
"""
from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import sqlalchemy as sa
from sqlalchemy import Select, select, tuple_
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.sql.elements import ColumnElement

from app.models.events import Event
from app.models.markings import TlpMarking
from app.models.sources import Source
from app.models.tags import AttackTechniqueTag

FeedType = Literal["rss", "taxii", "nvd"]
TlpName = Literal["clear", "green", "amber", "amber+strict", "red"]


@dataclass
class EventsQueryParams:
    source: list[uuid.UUID] | None = None
    source_type: list[str] | None = None
    observed_from: datetime | None = None
    observed_to: datetime | None = None
    tlp: list[str] | None = None
    attack_technique: list[str] | None = None
    tag: list[str] | None = None
    include_archived: bool = False
    has_geo: bool = False
    tag_mode: Literal["any", "all"] = "all"


class CursorError(ValueError):
    """Raised on malformed cursor input. Routers convert to HTTP 400."""


def encode_cursor(observed_at: datetime, event_id: uuid.UUID) -> str:
    raw = f"{observed_at.isoformat()}|{event_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        ts_str, id_str = raw.rsplit("|", 1)
        return datetime.fromisoformat(ts_str), uuid.UUID(id_str)
    except Exception as exc:  # noqa: BLE001
        raise CursorError(f"invalid cursor: {exc}") from exc


def build_events_query(
    params: EventsQueryParams,
    dashboard_roles: list[str] | None,
    project_id: uuid.UUID | None = None,
    scope_predicate: ColumnElement[bool] | None = None,
    bound_sources: list[uuid.UUID] | None = None,
) -> Select:
    """Compose a Select of Event rows honouring dashboard_roles + project filters.

    Phase 10 kwargs (all default None — unchanged when omitted, preserving Phase 9
    dashboard contract):
      project_id: when set, filters events.project_id = project_id
      scope_predicate: when set, applies the scope-intersection predicate
        (router pre-builds via app.services.project_scope.build_scope_predicate)
      bound_sources: when non-empty, filters events.source_id IN (bound_sources)
        (router pre-builds via app.services.project_scope.fetch_bound_sources)
    """
    stmt: Select = select(Event)

    if params.source:
        stmt = stmt.where(Event.source_id.in_(params.source))

    if params.source_type:
        stmt = stmt.where(
            Event.source_id.in_(
                select(Source.id).where(Source.feed_type.in_(params.source_type))
            )
        )

    if params.observed_from:
        stmt = stmt.where(Event.observed_at >= params.observed_from)

    if params.observed_to:
        stmt = stmt.where(Event.observed_at <= params.observed_to)

    if params.tlp:
        stmt = stmt.where(
            Event.tlp_marking_id.in_(
                select(TlpMarking.id).where(TlpMarking.name.in_(params.tlp))
            )
        )

    if params.attack_technique:
        stmt = stmt.where(
            Event.id.in_(
                select(AttackTechniqueTag.event_id).where(
                    AttackTechniqueTag.technique_id.in_(params.attack_technique)
                )
            )
        )

    if params.tag:
        #: COALESCE NULL tags to empty array so untagged rows are NOT
        # silently excluded — NULL @> ARRAY[...] = NULL which never matches WHERE.
        #: tag_mode='any' uses && (overlap); tag_mode='all' (default) uses @> (contains).
        op_token = "&&" if params.tag_mode == "any" else "@>"
        stmt = stmt.where(
            sa.func.coalesce(
                Event.tags,
                sa.cast(sa.literal("{}"), ARRAY(sa.Text)),
            ).op(op_token)(sa.cast(params.tag, ARRAY(sa.Text)))
        )

    if not params.include_archived:
        stmt = stmt.where(Event.archived == False)  # noqa: E712

    # MAP-01: filter to only events with resolved geo coordinates
    if params.has_geo:
        stmt = stmt.where(Event.geo_lat.isnot(None)).where(Event.geo_lon.isnot(None))

    # Visibility gating by dashboard_roles claim (AUTH-02 / C-2 closure).
    # dashboard_roles comes from request.state.user.dashboard_roles (populated by AuthMiddleware
    # from the JWT claim). Dashboard role header trust removed at the service layer (plan 09-05).
    # Empty / None list = unauthenticated (AUTH_ENABLED=false) or admin view -> no filter.
    if dashboard_roles:
        allowed: list[str] = ["shared"]
        if "red" in dashboard_roles:
            allowed.append("red_only")
        if "blue" in dashboard_roles:
            allowed.append("blue_only")
        stmt = stmt.where(Event.visibility.in_(allowed))

    # Phase 10 / PRJ-03: project_id narrowing + bound-sources + scope-intersection
    # Applied AFTER role gating so cross-cutting filters compose correctly.
    if project_id is not None:
        stmt = stmt.where(Event.project_id == project_id)
        if bound_sources:
            stmt = stmt.where(Event.source_id.in_(bound_sources))
        if scope_predicate is not None:
            stmt = stmt.where(scope_predicate)

    stmt = stmt.order_by(Event.observed_at.desc(), Event.id.desc())
    return stmt


def apply_cursor(stmt: Select, cursor_ts: datetime, cursor_id: uuid.UUID) -> Select:
    """Append keyset pagination WHERE clause for (observed_at, id) < (cursor_ts, cursor_id)."""
    return stmt.where(
        tuple_(Event.observed_at, Event.id) < (cursor_ts, cursor_id)
    )


# ---------------------------------------------------------------------------
# FTS path (FIL-05)
# ---------------------------------------------------------------------------


def _rank_expression(q: str):
    """ts_rank_cd(search_tsv, plainto_tsquery('english', q)) — SQL column expression."""
    tsquery = sa.func.plainto_tsquery("english", q)
    return sa.func.ts_rank_cd(sa.column("search_tsv"), tsquery)


def build_fts_query(
    params: EventsQueryParams,
    dashboard_roles: list[str] | None,
    q: str,
    project_id: uuid.UUID | None = None,
    scope_predicate: ColumnElement[bool] | None = None,
    bound_sources: list[uuid.UUID] | None = None,
) -> Select:
    """FTS variant of build_events_query.

 Adds WHERE search_tsv @@ plainto_tsquery('english',:q) and
 ORDER BY ts_rank_cd DESC, observed_at DESC, id DESC.
 The select projects (Event, rank) so routers can read rank off rows for cursor.

 Phase 10 kwargs (all default None): see build_events_query for semantics.
"""
    if not q or not q.strip():
        raise ValueError("free_text query cannot be empty")

    rank_col = _rank_expression(q).label("rank")
    tsquery = sa.func.plainto_tsquery("english", q)

    stmt: Select = select(Event, rank_col).where(
        sa.column("search_tsv").op("@@")(tsquery)
    )

    if params.source:
        stmt = stmt.where(Event.source_id.in_(params.source))
    if params.source_type:
        stmt = stmt.where(
            Event.source_id.in_(
                select(Source.id).where(Source.feed_type.in_(params.source_type))
            )
        )
    if params.observed_from:
        stmt = stmt.where(Event.observed_at >= params.observed_from)
    if params.observed_to:
        stmt = stmt.where(Event.observed_at <= params.observed_to)
    if params.tlp:
        stmt = stmt.where(
            Event.tlp_marking_id.in_(
                select(TlpMarking.id).where(TlpMarking.name.in_(params.tlp))
            )
        )
    if params.attack_technique:
        stmt = stmt.where(
            Event.id.in_(
                select(AttackTechniqueTag.event_id).where(
                    AttackTechniqueTag.technique_id.in_(params.attack_technique)
                )
            )
        )
    if params.tag:
        #: COALESCE NULL tags so untagged rows are not silently included
        #: tag_mode='any' uses && (overlap); tag_mode='all' (default) uses @> (contains).
        op_token = "&&" if params.tag_mode == "any" else "@>"
        stmt = stmt.where(
            sa.func.coalesce(
                Event.tags,
                sa.cast(sa.literal("{}"), ARRAY(sa.Text)),
            ).op(op_token)(sa.cast(params.tag, ARRAY(sa.Text)))
        )
    if not params.include_archived:
        stmt = stmt.where(Event.archived == False)  # noqa: E712
    # MAP-01: filter to only events with resolved geo coordinates
    if params.has_geo:
        stmt = stmt.where(Event.geo_lat.isnot(None)).where(Event.geo_lon.isnot(None))
    # Visibility gating by dashboard_roles claim (AUTH-02 / C-2 closure).
    # Dashboard role header trust removed at the service layer (plan 09-05).
    # Empty / None list = unauthenticated (AUTH_ENABLED=false) or admin view -> no filter.
    if dashboard_roles:
        allowed: list[str] = ["shared"]
        if "red" in dashboard_roles:
            allowed.append("red_only")
        if "blue" in dashboard_roles:
            allowed.append("blue_only")
        stmt = stmt.where(Event.visibility.in_(allowed))

    # Phase 10 / PRJ-03: project_id narrowing + bound-sources + scope-intersection
    if project_id is not None:
        stmt = stmt.where(Event.project_id == project_id)
        if bound_sources:
            stmt = stmt.where(Event.source_id.in_(bound_sources))
        if scope_predicate is not None:
            stmt = stmt.where(scope_predicate)

    stmt = stmt.order_by(rank_col.desc(), Event.observed_at.desc(), Event.id.desc())
    return stmt


def encode_fts_cursor(rank: float, observed_at: datetime, event_id: uuid.UUID) -> str:
    raw = f"{rank:.8f}|{observed_at.isoformat()}|{event_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_fts_cursor(cursor: str) -> tuple[float, datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        parts = raw.split("|")
        if len(parts) != 3:
            raise CursorError("FTS cursor must have 3 parts")
        rank = float(parts[0])
        ts = datetime.fromisoformat(parts[1])
        eid = uuid.UUID(parts[2])
        return rank, ts, eid
    except CursorError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise CursorError(f"invalid FTS cursor: {exc}") from exc


def apply_fts_cursor(
    stmt: Select, q: str, cursor_rank: float, cursor_ts: datetime, cursor_id: uuid.UUID
) -> Select:
    """Append tuple comparison (rank, observed_at, id) < (...) to an FTS stmt."""
    rank_col = _rank_expression(q)
    return stmt.where(
        tuple_(rank_col, Event.observed_at, Event.id)
        < (cursor_rank, cursor_ts, cursor_id)
    )
