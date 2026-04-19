"""GET /api/events/{id}/graph — Cytoscape-ready graph response."""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.database import get_session
from app.schemas.graph import GraphResponse
from app.services.graph_traversal import (
    DEFAULT_DEPTH,
    MAX_DEPTH,
    MIN_DEPTH,
    traverse_graph,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/events", tags=["graph"])


@router.get("/{event_id}/graph", response_model=GraphResponse)
async def get_event_graph(
    event_id: uuid.UUID,
    request: Request,
    depth: int = Query(default=DEFAULT_DEPTH, ge=MIN_DEPTH, le=MAX_DEPTH),
    db: AsyncSession = Depends(get_session),
) -> GraphResponse:
    # AUTH-02 / C-2: dashboard_roles sourced from JWT claim (request.state.user),
    # populated by AuthMiddleware. Dashboard role header removed (plan 09-05).
    # When AUTH_ENABLED=false, request.state.user is unset → dashboard_roles=None → no filter.
    user = getattr(request.state, "user", None)
    dashboard_roles: list[str] | None = list(user.dashboard_roles) if user is not None else None

    try:
        result = await traverse_graph(db, event_id, depth=depth, dashboard_roles=dashboard_roles)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="event not found")
    log.info(
        "graph_queried",
        event_id=str(event_id),
        depth=depth,
        node_count=len(result.nodes),
        edge_count=len(result.edges),
        truncated=result.truncated,
    )
    return GraphResponse(
        nodes=result.nodes,  # type: ignore[arg-type]
        edges=result.edges,  # type: ignore[arg-type]
        truncated=result.truncated,
    )
