"""Campaigns REST API - ACTOR-03.

Endpoints:
  GET    /api/campaigns                          list campaigns (project-scoped; Lead+ sees global too)
  POST   /api/campaigns                          create campaign (Lead+)
  PATCH  /api/campaigns/{campaign_id}            update campaign (Lead+)
  DELETE /api/campaigns/{campaign_id}            delete campaign (Lead+)
  POST   /api/campaigns/{campaign_id}/events/{event_id}   link event (Lead+)
  DELETE /api/campaigns/{campaign_id}/events/{event_id}   unlink event (Lead+)

Visibility rule (CONTEXT.md locked decision):
  Lead+ / Admin:   WHERE project_id = :pid OR project_id IS NULL
  Contributor:     WHERE project_id = :pid
"""
from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.database import get_session
from app.middleware.auth import require_auth
from app.models.actors import Campaign, CampaignEvent
from app.schemas.actors import CampaignCreate, CampaignListResponse, CampaignPatch, CampaignRead
from app.security.jwt import AuthUser
from app.services.audit import log_audit

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

_LEAD_RANK = 3  # PROJECT_ROLE_RANK["Lead"]


# ---------------------------------------------------------------------------
# RBAC helpers (mirrors actors.py pattern)
# ---------------------------------------------------------------------------


def _is_lead_or_above(user: AuthUser) -> bool:
    """Return True when user has Lead+ on any project, or is a global Admin."""
    if user.role == "Admin":
        return True
    pm: dict[str, int] = getattr(user, "project_memberships", None) or {}
    return any(rank >= _LEAD_RANK for rank in pm.values())


def _require_lead_or_above(user: AuthUser = Depends(require_auth)) -> AuthUser:
    if not _is_lead_or_above(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient_role")
    return user


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=CampaignListResponse)
async def list_campaigns(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    user: AuthUser = Depends(require_auth),
    project_id: uuid.UUID = Query(..., description="Project context for visibility filter."),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
) -> CampaignListResponse:
    """List campaigns.

    Lead+ / Admin: global campaigns (project_id IS NULL) + project-scoped campaigns.
    Contributor / Observer: project-scoped campaigns only.
    """
    stmt = select(Campaign)

    if _is_lead_or_above(user):
        # Lead+ sees global AND project-specific campaigns
        stmt = stmt.where(
            or_(Campaign.project_id == project_id, Campaign.project_id.is_(None))
        )
    else:
        # Contributor / Observer: project-scoped only
        stmt = stmt.where(Campaign.project_id == project_id)

    if cursor:
        try:
            stmt = stmt.where(Campaign.id > uuid.UUID(cursor))
        except ValueError:
            pass

    stmt = stmt.order_by(Campaign.id.asc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    next_cursor: str | None = None
    if len(rows) > limit:
        next_cursor = str(rows[limit - 1].id)
        rows = rows[:limit]

    return CampaignListResponse(items=rows, next_cursor=next_cursor)  # type: ignore[arg-type]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CampaignRead)
async def create_campaign(
    body: CampaignCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    _user: AuthUser = Depends(_require_lead_or_above),
) -> Campaign:
    """Create a campaign. Lead+ only."""
    user_sub = getattr(request.state.user, "id", None)
    request_id = getattr(request.state, "correlation_id", None)

    campaign = Campaign(
        id=uuid.uuid4(),
        name=body.name,
        actor_id=body.actor_id,
        start_date=body.start_date,
        end_date=body.end_date,
        summary_md=body.summary_md,
        project_id=body.project_id,
        created_by_user_sub=user_sub,
    )
    db.add(campaign)

    log_audit(
        db,
        action="create",
        resource_type="campaign",
        resource_id=str(campaign.id),
        user_sub=user_sub,
        request_id=request_id,
        project_id=body.project_id,
        after={"name": campaign.name, "project_id": str(body.project_id) if body.project_id else None},
    )

    await db.commit()
    await db.refresh(campaign)
    log.info("campaign_created", campaign_id=str(campaign.id), user_sub=user_sub)
    return campaign


@router.patch("/{campaign_id}", response_model=CampaignRead)
async def patch_campaign(
    campaign_id: uuid.UUID,
    body: CampaignPatch,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    _user: AuthUser = Depends(_require_lead_or_above),
) -> Campaign:
    """Update campaign fields. Lead+ only."""
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="campaign_not_found")

    before = {
        "name": campaign.name,
        "actor_id": str(campaign.actor_id) if campaign.actor_id else None,
        "start_date": campaign.start_date.isoformat() if campaign.start_date else None,
        "end_date": campaign.end_date.isoformat() if campaign.end_date else None,
        "summary_md": campaign.summary_md,
    }

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(campaign, field, value)

    after = {
        "name": campaign.name,
        "actor_id": str(campaign.actor_id) if campaign.actor_id else None,
        "start_date": campaign.start_date.isoformat() if campaign.start_date else None,
        "end_date": campaign.end_date.isoformat() if campaign.end_date else None,
        "summary_md": campaign.summary_md,
    }

    user_sub = getattr(request.state.user, "id", None)
    request_id = getattr(request.state, "correlation_id", None)
    log_audit(
        db,
        action="update",
        resource_type="campaign",
        resource_id=str(campaign.id),
        user_sub=user_sub,
        request_id=request_id,
        project_id=campaign.project_id,
        before=before,
        after=after,
    )

    await db.commit()
    await db.refresh(campaign)
    log.info("campaign_updated", campaign_id=str(campaign.id), fields=list(update_data.keys()))
    return campaign


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_campaign(
    campaign_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    _user: AuthUser = Depends(_require_lead_or_above),
) -> Response:
    """Delete a campaign and its campaign_events rows (CASCADE). Lead+ only."""
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="campaign_not_found")

    before = {"name": campaign.name, "project_id": str(campaign.project_id) if campaign.project_id else None}
    user_sub = getattr(request.state.user, "id", None)
    request_id = getattr(request.state, "correlation_id", None)

    log_audit(
        db,
        action="delete",
        resource_type="campaign",
        resource_id=str(campaign.id),
        user_sub=user_sub,
        request_id=request_id,
        project_id=campaign.project_id,
        before=before,
        after=None,
    )

    await db.delete(campaign)
    await db.commit()
    log.info("campaign_deleted", campaign_id=str(campaign_id), user_sub=user_sub)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{campaign_id}/events/{event_id}")
async def link_event_to_campaign(
    campaign_id: uuid.UUID,
    event_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    _user: AuthUser = Depends(_require_lead_or_above),
) -> dict:
    """Link an event to a campaign (idempotent). Lead+ only.

    Uses INSERT ON CONFLICT DO NOTHING for idempotency.
    """
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="campaign_not_found")

    user_sub = getattr(request.state.user, "id", None)
    request_id = getattr(request.state, "correlation_id", None)

    # Idempotent insert
    stmt = (
        pg_insert(CampaignEvent)
        .values(
            campaign_id=campaign_id,
            event_id=event_id,
            linked_by_user_sub=user_sub,
        )
        .on_conflict_do_nothing(index_elements=["campaign_id", "event_id"])
    )
    await db.execute(stmt)

    log_audit(
        db,
        action="create",
        resource_type="campaign_event",
        resource_id=f"{campaign_id}:{event_id}",
        user_sub=user_sub,
        request_id=request_id,
        project_id=campaign.project_id,
        after={"campaign_id": str(campaign_id), "event_id": str(event_id)},
    )

    await db.commit()
    log.info("campaign_event_linked", campaign_id=str(campaign_id), event_id=str(event_id))
    return {"linked": True}


@router.delete("/{campaign_id}/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def unlink_event_from_campaign(
    campaign_id: uuid.UUID,
    event_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    _user: AuthUser = Depends(_require_lead_or_above),
) -> Response:
    """Unlink an event from a campaign. Lead+ only."""
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="campaign_not_found")

    user_sub = getattr(request.state.user, "id", None)
    request_id = getattr(request.state, "correlation_id", None)

    log_audit(
        db,
        action="delete",
        resource_type="campaign_event",
        resource_id=f"{campaign_id}:{event_id}",
        user_sub=user_sub,
        request_id=request_id,
        project_id=campaign.project_id,
        before={"campaign_id": str(campaign_id), "event_id": str(event_id)},
    )

    await db.execute(
        delete(CampaignEvent).where(
            CampaignEvent.campaign_id == campaign_id,
            CampaignEvent.event_id == event_id,
        )
    )
    await db.commit()
    log.info("campaign_event_unlinked", campaign_id=str(campaign_id), event_id=str(event_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
