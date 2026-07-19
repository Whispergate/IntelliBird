"""Brand Protection router.

Endpoints (all mounted at /api prefix in main.py):

  GET    /api/projects/{project_id}/brand/terms
  POST   /api/projects/{project_id}/brand/terms
  PATCH  /api/projects/{project_id}/brand/terms/{term_id}
  GET    /api/projects/{project_id}/brand/matches
  PATCH  /api/projects/{project_id}/brand/matches/{match_id}
  POST   /api/projects/{project_id}/brand/matches/{match_id}/extend
  GET /api/projects/{project_id}/brand/matches/{match_id}/details (BRAND-02)
  GET    /api/projects/{project_id}/brand/suppression-review
  GET    /api/projects/{project_id}/brand/preview

Authority matrix (12-CONTEXT.md §Authority matrix):

                               | keyword/domain/product | person
  Global Admin                 |    ✓                   |  ✓
  Global Analyst               |    ✓                   |  ✗
  Global Viewer                |    ✗                   |  ✗
  Project Lead                 |    ✓                   |  ✓
  Project Contributor          |    ✓                   |  ✗
  Project Observer             |    ✗                   |  ✗

Observer is strictly read-only across all endpoints (PATCH/POST routes require
require_analyst_or_above OR Contributor+ project rank).
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_auth
from app.models.projects import ProjectRole
from app.schemas.brand import (
    AggregateCounts,
    BrandDashboardResponse,
    BrandMatchPatch,
    BrandMatchRead,
    BrandPreviewResponse,
    BrandStoplistTermCreate,
    BrandStoplistTermRead,
    BrandSuppressionExtend,
    BrandSuppressionRow,
    BrandTermCreate,
    BrandTermPatch,
    BrandTermRead,
    HistoryEntry,
    MatchDetailsResponse,
    MatchProvenance,
)
from app.security.jwt import PROJECT_ROLE_RANK, AuthUser
from app.security.project_membership import require_project_membership
from app.services.brand_preview import preview_term as brand_preview_term
from app.services.brand_stoplist import is_stoplisted
from app.models.brand import BrandStoplistTerm
from app.services.redis_client import get_redis

log = structlog.get_logger(__name__)
brand_log = logging.getLogger("app.brand")

router = APIRouter(tags=["brand"])

_OBSERVER_RANK = PROJECT_ROLE_RANK["Observer"]
_CONTRIBUTOR_RANK = PROJECT_ROLE_RANK["Contributor"]
_LEAD_RANK = PROJECT_ROLE_RANK["Lead"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _project_rank(user: AuthUser, project_id: UUID) -> int:
    """Return the caller's numeric project rank (0 = no membership)."""
    return user.project_memberships.get(str(project_id), 0)


def _require_modifier(user: AuthUser, project_id: UUID) -> None:
    """Observer-block guard for PATCH/POST routes (non-person endpoints).

    Allows: global Admin, global Analyst, or project Contributor+.
    Rejects Observer on both global (Viewer) and project (rank 1) axes.
    """
    if user.role in {"Admin", "Analyst"}:
        return
    if _project_rank(user, project_id) >= _CONTRIBUTOR_RANK:
        return
    raise HTTPException(
        status_code=403,
        detail="Observers cannot modify brand resources.",
    )


def _can_create_person_term(user: AuthUser, project_id: UUID) -> bool:
    """Person-type term authority: global Admin OR project Lead only."""
    if user.role == "Admin":
        return True
    if _project_rank(user, project_id) >= _LEAD_RANK:
        return True
    return False


# ---------------------------------------------------------------------------
# GET /terms
# ---------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/brand/terms",
    response_model=list[BrandTermRead],
)
async def list_terms(
    project_id: UUID,
    include_archived: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
) -> list[BrandTermRead]:
    """List brand terms for a project with 24h match counts.

    LATERAL-join pattern equivalent: correlated subquery computes matches_24h
    per term so the UI can flag noisy terms without a second round-trip.
    """
    sql = text(
        """
        SELECT bt.id, bt.project_id, bt.term_type, bt.value, bt.mode, bt.archived,
               bt.high_noise_risk, bt.created_by, bt.created_at,
               (SELECT COUNT(*) FROM brand_matches bm
                WHERE bm.brand_term_id = bt.id
                  AND bm.last_seen > NOW() - INTERVAL '24 hours') AS matches_24h
        FROM brand_terms bt
        WHERE bt.project_id = CAST(:pid AS uuid)
          AND (:include_archived OR bt.archived = false)
        ORDER BY bt.created_at DESC
        """
    )
    rows = (
        await session.execute(
            sql,
            {"pid": str(project_id), "include_archived": include_archived},
        )
    ).mappings().all()
    return [BrandTermRead(**dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# POST /terms
# ---------------------------------------------------------------------------

@router.post(
    "/projects/{project_id}/brand/terms",
    response_model=BrandTermRead,
    status_code=201,
)
async def create_term(
    project_id: UUID,
    body: BrandTermCreate,
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(require_auth),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
) -> BrandTermRead:
    """Create a new brand term.

    Authority:
      - keyword/domain/product: Admin, Analyst, Project Contributor+, Project Lead
      - person:                 Admin OR Project Lead only (GDPR liability)

    Person-type requires ``gdpr_consent=true`` in the body; rejected with 422
    otherwise. Duplicate (case-insensitive) returns 409.
    """
    # Observer check (covers global Viewer + project Observer)
    _require_modifier(user, project_id)

    if body.term_type == "person":
        if not _can_create_person_term(user, project_id):
            raise HTTPException(
                status_code=403,
                detail="Creating person-type terms requires Lead or Admin role.",
            )
        if not body.gdpr_consent:
            raise HTTPException(
                status_code=422,
                detail="gdpr_consent is required for person-type terms.",
            )

    # High-noise-risk flag pre-computed from stoplist (canonical for later
    # preview / dashboard banners).
    high_noise = is_stoplisted(body.value)

    try:
        row = (
            await session.execute(
                text(
                    """
                    INSERT INTO brand_terms (
                        project_id, term_type, value, high_noise_risk, created_by
                    )
                    VALUES (
                        CAST(:pid AS uuid), :term_type, :value,
                        :high_noise, :sub
                    )
                    RETURNING id, project_id, term_type, value, mode, archived,
                              high_noise_risk, created_by, created_at
                    """
                ),
                {
                    "pid": str(project_id),
                    "term_type": body.term_type,
                    "value": body.value,
                    "high_noise": high_noise,
                    "sub": user.id,
                },
            )
        ).mappings().one()
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="This term already exists for this project.",
        )

    # Structured GDPR-consent log for person-type terms (12-CONTEXT.md §Person-type
    # auditability). Hash the value so logs never leak plaintext PII.
    if body.term_type == "person":
        brand_log.info(
            "brand_term_person_consent",
            extra={
                "user_sub": user.id,
                "project_id": str(project_id),
                "term_value_hash": hashlib.sha256(
                    body.value.encode()
                ).hexdigest(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    return BrandTermRead(**dict(row))


# ---------------------------------------------------------------------------
# PATCH /terms/{term_id}
# ---------------------------------------------------------------------------

@router.patch(
    "/projects/{project_id}/brand/terms/{term_id}",
    response_model=BrandTermRead,
)
async def patch_term(
    project_id: UUID,
    term_id: UUID,
    body: BrandTermPatch,
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(require_auth),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
) -> BrandTermRead:
    """Update brand term mode or archived flag. Value + type are immutable."""
    _require_modifier(user, project_id)

    sets: list[str] = []
    params: dict[str, object] = {"pid": str(project_id), "tid": str(term_id)}
    if body.mode is not None:
        sets.append("mode = :mode")
        params["mode"] = body.mode
    if body.archived is not None:
        sets.append("archived = :archived")
        params["archived"] = body.archived
    if not sets:
        raise HTTPException(status_code=422, detail="No fields to update.")

    sql = text(
        f"""
        UPDATE brand_terms SET {', '.join(sets)}
        WHERE id = CAST(:tid AS uuid)
          AND project_id = CAST(:pid AS uuid)
        RETURNING id, project_id, term_type, value, mode, archived,
                  high_noise_risk, created_by, created_at
        """
    )
    row = (await session.execute(sql, params)).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Term not found.")
    await session.commit()
    return BrandTermRead(**dict(row))


# ---------------------------------------------------------------------------
# GET /matches (dashboard payload)
# ---------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/brand/matches",
    response_model=BrandDashboardResponse,
)
async def list_matches(
    project_id: UUID,
    severity: str | None = Query(default=None),
    source: str | None = Query(default=None),
    lifecycle: str | None = Query(default=None),
    include_dismissed: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
) -> BrandDashboardResponse:
    """Project brand-matches dashboard payload.

    Filters (all optional): severity, match source, lifecycle status.
    ``include_dismissed`` defaults false; when a ``lifecycle`` filter is set
    the include_dismissed flag is ignored (explicit lifecycle wins).

    Response includes two banner flags:
      * has_expiring_dismissals     - dismissals expiring in the next 7 days
      * has_recent_auto_downgrade   - >0 terms flipped to watch_only recently
    """
    filters: list[str] = ["bm.project_id = CAST(:pid AS uuid)"]
    params: dict[str, object] = {"pid": str(project_id)}
    if severity:
        filters.append("bm.severity = :severity")
        params["severity"] = severity
    if source:
        filters.append("bm.match_source = :source")
        params["source"] = source
    if lifecycle:
        filters.append("bm.lifecycle_status = :lifecycle")
        params["lifecycle"] = lifecycle
    elif not include_dismissed:
        filters.append("bm.lifecycle_status <> 'dismissed'")

    sql = text(
        f"""
        SELECT bm.id, bm.project_id, bm.brand_term_id,
               bt.value AS term_value, bt.term_type,
               bm.matched_value, bm.match_source, bm.severity,
               bm.first_seen, bm.last_seen, bm.lifecycle_status,
               bm.dismiss_until, bm.match_metadata
        FROM brand_matches bm
        JOIN brand_terms bt ON bt.id = bm.brand_term_id
        WHERE {' AND '.join(filters)}
        ORDER BY bm.last_seen DESC
        LIMIT 500
        """
    )
    rows = (await session.execute(sql, params)).mappings().all()
    matches = [BrandMatchRead(**dict(r)) for r in rows]

    # has_expiring_dismissals - any dismissed row with dismiss_until in <7d
    exp_row = (
        await session.execute(
            text(
                """
                SELECT COUNT(*) AS cnt FROM brand_matches
                WHERE project_id = CAST(:pid AS uuid)
                  AND lifecycle_status = 'dismissed'
                  AND dismiss_until IS NOT NULL
                  AND dismiss_until < NOW() + INTERVAL '7 days'
                """
            ),
            {"pid": str(project_id)},
        )
    ).mappings().one()
    has_expiring = (exp_row["cnt"] or 0) > 0

    # has_recent_auto_downgrade - any active watch_only term in the project
    dg_rows = (
        await session.execute(
            text(
                """
                SELECT value FROM brand_terms
                WHERE project_id = CAST(:pid AS uuid)
                  AND mode = 'watch_only'
                  AND archived = false
                ORDER BY created_at DESC
                LIMIT 5
                """
            ),
            {"pid": str(project_id)},
        )
    ).mappings().all()
    dg_terms = [r["value"] for r in dg_rows]

    return BrandDashboardResponse(
        matches=matches,
        has_expiring_dismissals=has_expiring,
        has_recent_auto_downgrade=bool(dg_terms),
        recent_auto_downgrade_terms=dg_terms,
    )


# ---------------------------------------------------------------------------
# PATCH /matches/{match_id}
# ---------------------------------------------------------------------------

@router.patch(
    "/projects/{project_id}/brand/matches/{match_id}",
    response_model=BrandMatchRead,
)
async def patch_match(
    project_id: UUID,
    match_id: UUID,
    body: BrandMatchPatch,
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(require_auth),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
) -> BrandMatchRead:
    """Update lifecycle status of a brand match.

    Transitions: new | confirmed | dismissed | watchlist.
    ``dismissed`` sets dismiss_until = NOW() + dismiss_days (default 30 days).
    ``new`` clears dismiss_until. Other states leave dismiss_until untouched.

    BRAND-02: optional ``note`` (max 500 chars) is embedded in the
    history entry appended to match_metadata.history[]. Uses jsonb_set so
    existing detector provenance keys (event_id, issuer, fuzzer, etc.) are
    never clobbered.
    """
    _require_modifier(user, project_id)

    # Fetch current lifecycle_status for history prev_status
    existing_row = (
        await session.execute(
            text(
                """
                SELECT lifecycle_status FROM brand_matches
                WHERE id = CAST(:mid AS uuid)
                  AND project_id = CAST(:pid AS uuid)
                """
            ),
            {"mid": str(match_id), "pid": str(project_id)},
        )
    ).mappings().first()
    if not existing_row:
        raise HTTPException(status_code=404, detail="Match not found.")

    prev_status = existing_row["lifecycle_status"]

    # Build history entry
    history_entry = {
        "acted_at": datetime.now(timezone.utc).isoformat(),
        "actor_id": user.id,
        "action": body.lifecycle_status,
        "prev_status": prev_status,
        "new_status": body.lifecycle_status,
        "note": body.note,
    }

    dismiss_until: datetime | None
    update_dismiss = False
    if body.lifecycle_status == "dismissed":
        days = body.dismiss_days if body.dismiss_days is not None else 30
        dismiss_until = datetime.now(timezone.utc) + timedelta(days=days)
        update_dismiss = True
    elif body.lifecycle_status == "new":
        dismiss_until = None
        update_dismiss = True
    else:
        dismiss_until = None  # unused

    if update_dismiss:
        sql = text(
            """
            UPDATE brand_matches bm
               SET lifecycle_status = :status,
                   dismiss_until = :du,
                   match_metadata = jsonb_set(
                       coalesce(bm.match_metadata, '{}'::jsonb),
                       '{history}',
                       coalesce(bm.match_metadata->'history', '[]'::jsonb) || CAST(:entry AS jsonb),
                       true
                   )
              FROM brand_terms bt
             WHERE bm.brand_term_id = bt.id
               AND bm.id = CAST(:mid AS uuid)
               AND bm.project_id = CAST(:pid AS uuid)
            RETURNING bm.id, bm.project_id, bm.brand_term_id,
                      bt.value AS term_value, bt.term_type,
                      bm.matched_value, bm.match_source, bm.severity,
                      bm.first_seen, bm.last_seen, bm.lifecycle_status,
                      bm.dismiss_until, bm.match_metadata
            """
        )
        params: dict[str, object] = {
            "status": body.lifecycle_status,
            "du": dismiss_until,
            "entry": json.dumps(history_entry),
            "mid": str(match_id),
            "pid": str(project_id),
        }
    else:
        sql = text(
            """
            UPDATE brand_matches bm
               SET lifecycle_status = :status,
                   match_metadata = jsonb_set(
                       coalesce(bm.match_metadata, '{}'::jsonb),
                       '{history}',
                       coalesce(bm.match_metadata->'history', '[]'::jsonb) || CAST(:entry AS jsonb),
                       true
                   )
              FROM brand_terms bt
             WHERE bm.brand_term_id = bt.id
               AND bm.id = CAST(:mid AS uuid)
               AND bm.project_id = CAST(:pid AS uuid)
            RETURNING bm.id, bm.project_id, bm.brand_term_id,
                      bt.value AS term_value, bt.term_type,
                      bm.matched_value, bm.match_source, bm.severity,
                      bm.first_seen, bm.last_seen, bm.lifecycle_status,
                      bm.dismiss_until, bm.match_metadata
            """
        )
        params = {
            "status": body.lifecycle_status,
            "entry": json.dumps(history_entry),
            "mid": str(match_id),
            "pid": str(project_id),
        }

    row = (await session.execute(sql, params)).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Match not found.")
    await session.commit()
    return BrandMatchRead(**dict(row))


# ---------------------------------------------------------------------------
# GET /matches/{match_id}/details - BRAND-02
# ---------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/brand/matches/{match_id}/details",
    response_model=MatchDetailsResponse,
)
async def get_match_details(
    project_id: UUID,
    match_id: UUID,
    session: AsyncSession = Depends(get_session),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
) -> MatchDetailsResponse:
    """Provenance + aggregate lifecycle counts + last-10 activity timeline.

    Observer+ read access. All queries scoped to (project_id, brand_term_id) -
    no cross-project data is accessible.

    Provenance: detector label, best-available raw_input per detector tier,
    matched_value, similarity (always None for current detectors).

    Aggregate counts: GROUP BY lifecycle_status across ALL matches for the same
    brand_term_id in this project (no lifecycle filter - includes dismissed).

    Timeline: flatten match_metadata.history[] from all sibling matches (same
    project_id + brand_term_id), sort descending by acted_at, cap at 10.
    """
    # Fetch the requested match (must exist in this project)
    match_row = (
        await session.execute(
            text(
                """
                SELECT bm.id, bm.project_id, bm.brand_term_id,
                       bm.matched_value, bm.match_source, bm.match_metadata
                FROM brand_matches bm
                WHERE bm.id = CAST(:mid AS uuid)
                  AND bm.project_id = CAST(:pid AS uuid)
                """
            ),
            {"mid": str(match_id), "pid": str(project_id)},
        )
    ).mappings().first()
    if not match_row:
        raise HTTPException(status_code=404, detail="Match not found.")

    brand_term_id = match_row["brand_term_id"]

    # Build provenance from match_source + match_metadata
    meta: dict = match_row["match_metadata"] or {}
    match_source: str = match_row["match_source"]
    if match_source == "fts":
        event_id_val = meta.get("event_id", "")
        raw_input = f"Event {str(event_id_val)[:8]}" if event_id_val else None
    elif match_source == "ct_log":
        raw_input = meta.get("issuer") or meta.get("not_before") or None
    elif match_source == "dnstwist":
        raw_input = meta.get("fuzzer") or None
    else:
        raw_input = None

    provenance = MatchProvenance(
        detector=match_source,
        raw_input=raw_input,
        matched_value=match_row["matched_value"],
        similarity=None,
    )

    # Fetch all sibling matches (same project_id + brand_term_id) - scoped query
    sibling_rows = (
        await session.execute(
            text(
                """
                SELECT id, matched_value, lifecycle_status, match_metadata
                FROM brand_matches
                WHERE project_id = CAST(:pid AS uuid)
                  AND brand_term_id = CAST(:tid AS uuid)
                """
            ),
            {"pid": str(project_id), "tid": str(brand_term_id)},
        )
    ).mappings().all()

    # Aggregate counts and timeline in a single pass
    counts: dict[str, int] = {"new": 0, "confirmed": 0, "dismissed": 0, "watchlist": 0}
    timeline_entries: list[dict] = []

    for row in sibling_rows:
        status = row["lifecycle_status"]
        if status in counts:
            counts[status] += 1
        row_meta: dict = row["match_metadata"] or {}
        for entry in row_meta.get("history", []):
            timeline_entries.append(
                {
                    **entry,
                    "match_id": str(row["id"]),
                    "matched_value": row["matched_value"],
                }
            )

    # Sort timeline descending by acted_at, cap at 10
    timeline_entries.sort(key=lambda e: e.get("acted_at", ""), reverse=True)
    timeline_top10 = timeline_entries[:10]

    return MatchDetailsResponse(
        match_id=match_row["id"],
        provenance=provenance,
        aggregate_counts=AggregateCounts(**counts),
        timeline=[HistoryEntry(**e) for e in timeline_top10],
    )


# ---------------------------------------------------------------------------
# POST /matches/{match_id}/extend
# ---------------------------------------------------------------------------

@router.post(
    "/projects/{project_id}/brand/matches/{match_id}/extend",
    response_model=BrandMatchRead,
)
async def extend_dismissal(
    project_id: UUID,
    match_id: UUID,
    body: BrandSuppressionExtend,
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(require_auth),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
) -> BrandMatchRead:
    """Extend / clear a dismissal or resurface a match.

    Semantics:
      let_resurface=True  → lifecycle_status='new',    dismiss_until=NULL
      extend_days=None    → dismiss_until=NULL   (Indefinite - status preserved)
      extend_days=N       → dismiss_until=NOW() + N days
    """
    _require_modifier(user, project_id)

    if body.let_resurface:
        sql = text(
            """
            UPDATE brand_matches bm
               SET lifecycle_status = 'new',
                   dismiss_until = NULL
              FROM brand_terms bt
             WHERE bm.brand_term_id = bt.id
               AND bm.id = CAST(:mid AS uuid)
               AND bm.project_id = CAST(:pid AS uuid)
            RETURNING bm.id, bm.project_id, bm.brand_term_id,
                      bt.value AS term_value, bt.term_type,
                      bm.matched_value, bm.match_source, bm.severity,
                      bm.first_seen, bm.last_seen, bm.lifecycle_status,
                      bm.dismiss_until, bm.match_metadata
            """
        )
        params: dict[str, object] = {
            "mid": str(match_id),
            "pid": str(project_id),
        }
    else:
        new_until: datetime | None
        if body.extend_days is None:
            new_until = None
        else:
            new_until = datetime.now(timezone.utc) + timedelta(days=body.extend_days)
        sql = text(
            """
            UPDATE brand_matches bm
               SET dismiss_until = :du
              FROM brand_terms bt
             WHERE bm.brand_term_id = bt.id
               AND bm.id = CAST(:mid AS uuid)
               AND bm.project_id = CAST(:pid AS uuid)
            RETURNING bm.id, bm.project_id, bm.brand_term_id,
                      bt.value AS term_value, bt.term_type,
                      bm.matched_value, bm.match_source, bm.severity,
                      bm.first_seen, bm.last_seen, bm.lifecycle_status,
                      bm.dismiss_until, bm.match_metadata
            """
        )
        params = {
            "du": new_until,
            "mid": str(match_id),
            "pid": str(project_id),
        }

    row = (await session.execute(sql, params)).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Match not found.")
    await session.commit()
    return BrandMatchRead(**dict(row))


# ---------------------------------------------------------------------------
# GET /suppression-review
# ---------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/brand/suppression-review",
    response_model=list[BrandSuppressionRow],
)
async def suppression_review(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
) -> list[BrandSuppressionRow]:
    """List dismissed matches whose dismiss_until falls within the next 7 days.

    Drives the 'Suppression Review' widget on the brand dashboard - operators
    get a short-horizon view of noise about to resurface.
    """
    rows = (
        await session.execute(
            text(
                """
                SELECT id, matched_value, match_source, dismiss_until
                FROM brand_matches
                WHERE project_id = CAST(:pid AS uuid)
                  AND lifecycle_status = 'dismissed'
                  AND dismiss_until IS NOT NULL
                  AND dismiss_until < NOW() + INTERVAL '7 days'
                ORDER BY dismiss_until ASC
                """
            ),
            {"pid": str(project_id)},
        )
    ).mappings().all()
    return [BrandSuppressionRow(**dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# GET /preview
# ---------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/brand/preview",
    response_model=BrandPreviewResponse,
)
async def preview(
    project_id: UUID,
    term: str = Query(..., min_length=1, max_length=200),
    term_type: Literal["keyword", "domain", "product", "person"] = Query(...),
    session: AsyncSession = Depends(get_session),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
) -> BrandPreviewResponse:
    """Test-coverage preview for a candidate brand term.

    Returns the FTS match count / percent against the last 1000 project
    events. Redis-cached for 60 seconds on (project, term, term_type).
    """
    redis = await get_redis()
    return await brand_preview_term(
        session=session,
        redis=redis,
        project_id=project_id,
        term=term,
        term_type=term_type,
    )


# ---------------------------------------------------------------------------
# GET /stoplist - BRAND-01
# ---------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/brand/stoplist",
    response_model=list[BrandStoplistTermRead],
)
async def list_stoplist(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
) -> list[BrandStoplistTermRead]:
    """List per-project brand stoplist terms. Observer+ read access."""
    rows = (
        await session.execute(
            select(BrandStoplistTerm)
            .where(BrandStoplistTerm.project_id == project_id)
            .order_by(BrandStoplistTerm.created_at.desc())
        )
    ).scalars().all()
    return [BrandStoplistTermRead.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# POST /stoplist - BRAND-01
# ---------------------------------------------------------------------------

@router.post(
    "/projects/{project_id}/brand/stoplist",
    response_model=BrandStoplistTermRead,
    status_code=201,
)
async def add_stoplist_term(
    project_id: UUID,
    body: BrandStoplistTermCreate,
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(require_auth),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
) -> BrandStoplistTermRead:
    """Add a term to the per-project brand stoplist. Lead+ only.

    Returns 409 on case-insensitive duplicate (same project_id + lower(term)).
    """
    term = BrandStoplistTerm(
        project_id=project_id,
        term=body.term,
        created_by_user_id=UUID(user.id) if user.id else None,
    )
    session.add(term)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Term already in stoplist for this project (case-insensitive duplicate).",
        )
    await session.refresh(term)
    return BrandStoplistTermRead.model_validate(term)


# ---------------------------------------------------------------------------
# DELETE /stoplist/{term_id} - BRAND-01
# ---------------------------------------------------------------------------

@router.delete(
    "/projects/{project_id}/brand/stoplist/{term_id}",
    status_code=204,
)
async def delete_stoplist_term(
    project_id: UUID,
    term_id: UUID,
    session: AsyncSession = Depends(get_session),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Lead)),
) -> Response:
    """Remove a per-project brand stoplist term. Lead+ only.

    Returns 404 if term_id not found within this project.
    Returns 204 No Content on success.
    """
    result = await session.execute(
        delete(BrandStoplistTerm)
        .where(
            BrandStoplistTerm.id == term_id,
            BrandStoplistTerm.project_id == project_id,
        )
        .returning(BrandStoplistTerm.id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Stoplist term not found.")
    await session.commit()
    return Response(status_code=204)
