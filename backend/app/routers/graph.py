"""GET /api/events/{id}/graph — Cytoscape-ready graph response."""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

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
    depth: int = Query(default=DEFAULT_DEPTH, ge=MIN_DEPTH, le=MAX_DEPTH),
    role: str | None = Header(default=None, alias="X-Dashboard-Role"),
    db: AsyncSession = Depends(get_session),
) -> GraphResponse:
    try:
        result = await traverse_graph(db, event_id, depth=depth, role=role)
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
