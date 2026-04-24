"""Brand Protection router (Phase 12).

Endpoints (all mounted at /api prefix in main.py):

  GET    /api/projects/{project_id}/brand/terms
  POST   /api/projects/{project_id}/brand/terms
  PATCH  /api/projects/{project_id}/brand/terms/{term_id}
  GET    /api/projects/{project_id}/brand/matches
  PATCH  /api/projects/{project_id}/brand/matches/{match_id}
  POST   /api/projects/{project_id}/brand/matches/{match_id}/extend
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
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import require_auth
from app.models.projects import ProjectRole
from app.schemas.brand import (
    BrandDashboardResponse,
    BrandMatchPatch,
    BrandMatchRead,
    BrandPreviewResponse,
    BrandSuppressionExtend,
    BrandSuppressionRow,
    BrandTermCreate,
    BrandTermPatch,
    BrandTermRead,
)
from app.security.jwt import PROJECT_ROLE_RANK, AuthUser
from app.security.project_membership import require_project_membership
from app.services.brand_preview import preview_term as brand_preview_term
from app.services.brand_stoplist import is_stoplisted
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
      * has_expiring_dismissals     — dismissals expiring in the next 7 days
      * has_recent_auto_downgrade   — >0 terms flipped to watch_only recently
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

    # has_expiring_dismissals — any dismissed row with dismiss_until in <7d
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

    # has_recent_auto_downgrade — any active watch_only term in the project
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
    """
    _require_modifier(user, project_id)

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
                   dismiss_until = :du
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
            "mid": str(match_id),
            "pid": str(project_id),
        }
    else:
        sql = text(
            """
            UPDATE brand_matches bm
               SET lifecycle_status = :status
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
            "mid": str(match_id),
            "pid": str(project_id),
        }

    row = (await session.execute(sql, params)).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Match not found.")
    await session.commit()
    return BrandMatchRead(**dict(row))


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
      extend_days=None    → dismiss_until=NULL   (Indefinite — status preserved)
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

    Drives the 'Suppression Review' widget on the brand dashboard — operators
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
