"""Threat actors REST API — Phase 25 / ACTOR-05, ACTOR-06.

Endpoints:
  GET  /api/actors                    paginated actor list
  GET  /api/actors/{actor_id}         actor profile
  GET  /api/actors/{actor_id}/graph   Cytoscape JSON {nodes, edges}
  POST /api/actors                    create actor (Lead+)
  PATCH /api/actors/{actor_id}        update actor (Lead+)

RBAC:
  Read endpoints — any authenticated user.
  Write endpoints (POST, PATCH) — Lead+ on any project, or Admin.
    Lead+ = user.role=="Admin" OR any project_memberships rank >= 3 (Lead).
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.database import get_session
from app.middleware.auth import require_auth
from app.models.actors import ActorEventLink, Campaign, CampaignEvent, ThreatActor
from app.models.events import Event
from app.models.iocs import IOC, IOCEventLink
from app.schemas.actors import ActorCreate, ActorListResponse, ActorPatch, ActorRead
from app.security.jwt import AuthUser
from app.services.audit import log_audit

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/actors", tags=["actors"])

_LEAD_RANK = 3  # PROJECT_ROLE_RANK["Lead"]


# ---------------------------------------------------------------------------
# RBAC helpers
# ---------------------------------------------------------------------------


def _is_lead_or_above(user: AuthUser) -> bool:
    """Return True when the user has Lead+ on any project or is a global Admin."""
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


@router.get("", response_model=ActorListResponse)
async def list_actors(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    _user: AuthUser = Depends(require_auth),
    q: str | None = Query(default=None, max_length=512, description="Search by primary_name (case-insensitive)."),
    country: str | None = Query(default=None),
    sophistication: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, description="Opaque cursor (actor primary_name keyset)."),
) -> ActorListResponse:
    """Paginated actor list with optional text/field filters."""
    stmt = select(ThreatActor)

    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(ThreatActor.primary_name).like(like))
    if country:
        stmt = stmt.where(ThreatActor.country == country)
    if sophistication:
        stmt = stmt.where(ThreatActor.sophistication == sophistication)

    # Cursor: keyset on (primary_name ASC, id ASC)
    if cursor:
        try:
            name_part, id_part = cursor.split("|", 1)
            stmt = stmt.where(
                or_(
                    ThreatActor.primary_name > name_part,
                    (ThreatActor.primary_name == name_part) & (ThreatActor.id > uuid.UUID(id_part)),
                )
            )
        except (ValueError, AttributeError):
            pass  # malformed cursor → ignore, return from beginning

    stmt = stmt.order_by(ThreatActor.primary_name.asc(), ThreatActor.id.asc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    next_cursor: str | None = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = f"{last.primary_name}|{last.id}"
        rows = rows[:limit]

    return ActorListResponse(items=rows, next_cursor=next_cursor, total=None)


@router.get("/{actor_id}", response_model=ActorRead)
async def get_actor(
    actor_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
    _user: AuthUser = Depends(require_auth),
) -> ThreatActor:
    """Actor profile detail. 404 if not found."""
    actor = await db.get(ThreatActor, actor_id)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="actor_not_found")
    return actor


@router.get("/{actor_id}/graph")
async def get_actor_graph(
    actor_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
    _user: AuthUser = Depends(require_auth),
) -> dict[str, list[dict[str, Any]]]:
    """Cytoscape graph centred on the actor.

    Node types: actor, campaign, event, technique, ioc.
    Edge types: PART_OF (event→campaign), USED_BY (technique→actor),
                SEEN_IN (ioc→event), ACTOR_LINK (event→actor).

    Total nodes capped at 100 to avoid frontend performance issues.
    """
    actor = await db.get(ThreatActor, actor_id)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="actor_not_found")

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    edge_counter = 0

    def _new_edge(source: str, target: str, label: str) -> dict[str, Any]:
        nonlocal edge_counter
        edge_counter += 1
        return {"data": {"id": f"e{edge_counter}", "source": source, "target": target, "label": label}}

    # Actor center node
    actor_node_id = f"actor-{actor.id}"
    nodes.append({"data": {"id": actor_node_id, "label": actor.primary_name, "type": "actor"}})

    # --- Campaigns linked to this actor ---
    campaigns_stmt = select(Campaign).where(Campaign.actor_id == actor_id).limit(20)
    campaigns = list((await db.execute(campaigns_stmt)).scalars().all())
    campaign_node_ids: set[str] = set()
    for campaign in campaigns:
        cnode_id = f"campaign-{campaign.id}"
        nodes.append({"data": {"id": cnode_id, "label": campaign.name, "type": "campaign"}})
        campaign_node_ids.add(cnode_id)
        edges.append(_new_edge(actor_node_id, cnode_id, "HAS_CAMPAIGN"))

    # --- Events via actor_event_links ---
    actor_link_stmt = (
        select(ActorEventLink.event_id)
        .where(ActorEventLink.actor_id == actor_id)
        .limit(30)
    )
    actor_link_event_ids = list((await db.execute(actor_link_stmt)).scalars().all())

    # --- Events via campaign_events (all campaigns for this actor) ---
    campaign_ids = [c.id for c in campaigns]
    campaign_event_ids: list[uuid.UUID] = []
    if campaign_ids:
        ce_stmt = (
            select(CampaignEvent.event_id)
            .where(CampaignEvent.campaign_id.in_(campaign_ids))
            .limit(30)
        )
        campaign_event_ids = list((await db.execute(ce_stmt)).scalars().all())

    # Merge event IDs, deduplicate, cap at 50
    all_event_ids = list({str(eid) for eid in actor_link_event_ids + campaign_event_ids})[:50]
    if not all_event_ids:
        return {"nodes": nodes, "edges": edges}

    event_ids_as_uuid = [uuid.UUID(eid) for eid in all_event_ids]
    events_stmt = select(Event).where(Event.id.in_(event_ids_as_uuid)).limit(50)
    events = list((await db.execute(events_stmt)).scalars().all())

    technique_node_ids: set[str] = set()
    ioc_node_ids: set[str] = set()

    for event in events:
        enode_id = f"event-{event.id}"
        nodes.append({
            "data": {
                "id": enode_id,
                "label": event.title or str(event.id),
                "type": "event",
            }
        })
        # Edge: event → actor (via actor_event_link)
        if str(event.id) in {str(eid) for eid in actor_link_event_ids}:
            edges.append(_new_edge(enode_id, actor_node_id, "ACTOR_LINK"))

        # Edge: event → campaign (if in campaign_events)
        if str(event.id) in {str(eid) for eid in campaign_event_ids}:
            # Find which campaign this event belongs to
            for c in campaigns:
                ce_check = await db.execute(
                    select(CampaignEvent.campaign_id)
                    .where(
                        CampaignEvent.campaign_id == c.id,
                        CampaignEvent.event_id == event.id,
                    )
                )
                if ce_check.scalars().first() is not None:
                    cnode_id = f"campaign-{c.id}"
                    edges.append(_new_edge(enode_id, cnode_id, "PART_OF"))
                    break

        # Technique nodes from events.attack_technique_ids
        technique_ids: list[str] = getattr(event, "attack_technique_ids", None) or []
        for tech_id in technique_ids[:5]:  # cap per-event
            tnode_id = f"technique-{tech_id}"
            if tnode_id not in technique_node_ids:
                technique_node_ids.add(tnode_id)
                nodes.append({
                    "data": {"id": tnode_id, "label": tech_id, "type": "technique"}
                })
            edges.append(_new_edge(tnode_id, actor_node_id, "USED_BY"))

    # IOC nodes via ioc_event_links
    if event_ids_as_uuid:
        ioc_link_stmt = (
            select(IOCEventLink.ioc_id, IOCEventLink.event_id)
            .where(IOCEventLink.event_id.in_(event_ids_as_uuid))
            .limit(30)
        )
        ioc_links = list((await db.execute(ioc_link_stmt)).all())
        ioc_ids_for_lookup = list({row.ioc_id for row in ioc_links})

        if ioc_ids_for_lookup:
            iocs_stmt = select(IOC).where(IOC.id.in_(ioc_ids_for_lookup)).limit(30)
            iocs = list((await db.execute(iocs_stmt)).scalars().all())
            ioc_by_id = {ioc.id: ioc for ioc in iocs}

            for link_row in ioc_links:
                ioc = ioc_by_id.get(link_row.ioc_id)
                if ioc is None:
                    continue
                inode_id = f"ioc-{ioc.id}"
                if inode_id not in ioc_node_ids:
                    ioc_node_ids.add(inode_id)
                    nodes.append({
                        "data": {
                            "id": inode_id,
                            "label": ioc.value or str(ioc.id),
                            "type": "ioc",
                        }
                    })
                enode_id = f"event-{link_row.event_id}"
                edges.append(_new_edge(inode_id, enode_id, "SEEN_IN"))

    # Cap total nodes at 100
    nodes = nodes[:100]

    log.info("actor_graph_built", actor_id=str(actor_id), node_count=len(nodes), edge_count=len(edges))
    return {"nodes": nodes, "edges": edges}


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ActorRead)
async def create_actor(
    body: ActorCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    _user: AuthUser = Depends(_require_lead_or_above),
) -> ThreatActor:
    """Create a new threat actor. Lead+ only."""
    actor = ThreatActor(
        id=uuid.uuid4(),
        primary_name=body.primary_name,
        aliases=body.aliases,
        country=body.country,
        motivation=body.motivation,
        sophistication=body.sophistication,
        first_seen=body.first_seen,
        profile_md=body.profile_md,
    )
    db.add(actor)

    user_sub = getattr(request.state.user, "id", None)
    request_id = getattr(request.state, "correlation_id", None)
    log_audit(
        db,
        action="create",
        resource_type="actor",
        resource_id=str(actor.id),
        user_sub=user_sub,
        request_id=request_id,
        after={"primary_name": actor.primary_name, "aliases": actor.aliases},
    )

    await db.commit()
    await db.refresh(actor)
    log.info("actor_created", actor_id=str(actor.id), user_sub=user_sub)
    return actor


@router.patch("/{actor_id}", response_model=ActorRead)
async def patch_actor(
    actor_id: uuid.UUID,
    body: ActorPatch,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    _user: AuthUser = Depends(_require_lead_or_above),
) -> ThreatActor:
    """Update actor fields. Lead+ only."""
    actor = await db.get(ThreatActor, actor_id)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="actor_not_found")

    before = {
        "primary_name": actor.primary_name,
        "aliases": actor.aliases,
        "country": actor.country,
        "motivation": actor.motivation,
        "sophistication": actor.sophistication,
        "first_seen": actor.first_seen.isoformat() if actor.first_seen else None,
        "profile_md": actor.profile_md,
    }

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(actor, field, value)

    after = {
        "primary_name": actor.primary_name,
        "aliases": actor.aliases,
        "country": actor.country,
        "motivation": actor.motivation,
        "sophistication": actor.sophistication,
        "first_seen": actor.first_seen.isoformat() if actor.first_seen else None,
        "profile_md": actor.profile_md,
    }

    user_sub = getattr(request.state.user, "id", None)
    request_id = getattr(request.state, "correlation_id", None)
    log_audit(
        db,
        action="update",
        resource_type="actor",
        resource_id=str(actor.id),
        user_sub=user_sub,
        request_id=request_id,
        before=before,
        after=after,
    )

    await db.commit()
    await db.refresh(actor)
    log.info("actor_updated", actor_id=str(actor.id), fields=list(update_data.keys()))
    return actor
