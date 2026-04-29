"""GET /api/events/{id}/graph — Cytoscape-ready graph response.
GET /api/projects/{id}/graph — project-aggregate multi-seed graph.
"""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.database import get_session
from app.middleware.auth import require_auth
from app.models.projects import ProjectRole
from app.schemas.graph import GraphResponse
from app.security.jwt import AuthUser
from app.security.project_membership import enforce_project_query_scope, require_project_membership
from app.services.graph_traversal import (
    DEFAULT_DEPTH,
    MAX_DEPTH,
    MIN_DEPTH,
    traverse_graph,
    traverse_project,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/events", tags=["graph"])

# Project-aggregate graph router — registered in main.py with prefix="/api"
# so the final path is /api/projects/{project_id}/graph.
projects_graph_router = APIRouter(prefix="/projects", tags=["graph"])


@router.get("/{event_id}/graph", response_model=GraphResponse)
async def get_event_graph(
    event_id: uuid.UUID,
    request: Request,
    depth: int = Query(default=DEFAULT_DEPTH, ge=MIN_DEPTH, le=MAX_DEPTH),
    project_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
) -> GraphResponse:
    # AUTH-02 / C-2: dashboard_roles sourced from JWT claim (request.state.user),
    # populated by AuthMiddleware. Dashboard role header removed (plan 09-05).
    # When AUTH_ENABLED=false, request.state.user is unset → dashboard_roles=None → no filter.
    user = getattr(request.state, "user", None)
    dashboard_roles: list[str] | None = list(user.dashboard_roles) if user is not None else None

    # PROD-01 GAP-2: enforce project membership at the router layer rather
    # than relying on graph_traversal's seed/project mismatch 404 (correct
    # result, wrong layer). Non-admin callers MUST specify project_id; the
    # helper 403s if the caller is not a member of the requested project,
    # or has no memberships at all.
    allowed_project_ids = enforce_project_query_scope(user, project_id)
    if allowed_project_ids is not None and project_id is None:
        raise HTTPException(
            status_code=400,
            detail="project_id query parameter required for non-admin callers",
        )

    # Phase 10 / PRJ-04: project_id query param narrows BFS to events in the
    # given project. traverse_graph re-applies project_id at every cross-event
    # expansion hop (H-3 enforcement).
    try:
        result = await traverse_graph(
            db, event_id, depth=depth,
            dashboard_roles=dashboard_roles,
            project_id=project_id,
        )
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


@projects_graph_router.get("/{project_id}/graph", response_model=GraphResponse)
async def project_graph(
    project_id: uuid.UUID,
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> GraphResponse:
    """Project-aggregate attack graph — Observer+ can view.

    Collects all project events via the build_scope_predicate chokepoint
    (build_events_query with project_id kwarg), then runs multi-seed BFS
    over Layer 1 (techniques) + Layer 2 (raw_stix SROs). Returns Cytoscape-
    ready nodes/edges with a truncated flag when the 1000-node / 5000-edge
    caps are hit.

    Security: require_project_membership enforces membership BEFORE any data
    is touched. Admin bypass returns ProjectRole.Lead transparently.
    """
    dashboard_roles: list[str] | None = list(user.dashboard_roles) if user.dashboard_roles else None

    result = await traverse_project(
        db,
        project_id,
        dashboard_roles=dashboard_roles,
        max_nodes=1000,
        max_edges=5000,
    )
    log.info(
        "project_graph_queried",
        project_id=str(project_id),
        node_count=len(result.nodes),
        edge_count=len(result.edges),
        truncated=result.truncated,
    )
    return GraphResponse(
        nodes=result.nodes,  # type: ignore[arg-type]
        edges=result.edges,  # type: ignore[arg-type]
        truncated=result.truncated,
    )
