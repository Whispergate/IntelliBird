"""GET /api/events/{id}/graph - Cytoscape-ready graph response.
GET /api/projects/{id}/graph - project-aggregate multi-seed graph.
GET /api/projects/{id}/graph/traverse - multi-hop AGE Cypher traversal.
"""
from __future__ import annotations

import json
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.database import get_session
from app.middleware.auth import require_auth
from app.models.projects import ProjectRole
from app.schemas.graph import GraphEdge, GraphEdgeData, GraphNode, GraphNodeData, GraphResponse
from app.security.jwt import AuthUser
from app.security.project_membership import enforce_project_query_scope, require_project_membership
from app.services.age_sync import _sanitize_uuid, age_conn
from app.services.graph_centrality import get_or_compute_centrality
from app.services.graph_traversal import (
    DEFAULT_DEPTH,
    MAX_DEPTH,
    MIN_DEPTH,
    NODE_CAP,
    traverse_graph,
    traverse_project,
)
from app.services.redis_client import get_redis

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/events", tags=["graph"])

# Project-aggregate graph router - registered in main.py with prefix="/api"
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

    # PRJ-04: project_id query param narrows BFS to events in the
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
    """Project-aggregate attack graph - Observer+ can view.

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


@projects_graph_router.get("/{project_id}/graph/traverse", response_model=GraphResponse)
async def traverse_domain_graph(
    project_id: uuid.UUID,
    seed_ioc_id: uuid.UUID = Query(..., description="UUID of a domain IOC to start traversal from"),
    hops: int = Query(default=2, ge=1, le=3, description="Number of hops (1-3)"),
    edge_filter: list[str] = Query(default=[], alias="edge_filter[]"),
    _role: ProjectRole = Depends(require_project_membership(ProjectRole.Observer)),
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> GraphResponse:
    """Multi-hop AGE Cypher traversal from a domain IOC seed.

    GRAPH-01 / GRAPH-04 / GRAPH-03:
    - Bounded BFS via AGE Cypher (:SHARES_INFRA | :SEEN_IN), LIMIT 200.
    - Cross-project isolation enforced via dual project_id predicate
      (vertex property + WHERE clause - belt-and-suspenders pattern).
    - Centrality (PageRank + betweenness) computed server-side via networkx
      and cached in Redis for 10 minutes.
    - Returns GraphResponse with per_node_centrality and centrality_truncated.
    - Existing /graph endpoint unchanged.
    """
    safe_pid = _sanitize_uuid(str(project_id))
    safe_ioc_id = _sanitize_uuid(str(seed_ioc_id))
    # Server-side clamp (belt-and-suspenders over Query ge/le constraint)
    hops = max(1, min(3, hops))

    # Build edge type filter for Cypher
    allowed_edge_types = {"SHARES_INFRA", "SEEN_IN"}
    if edge_filter:
        # Sanitize and intersect with allowed set
        requested = {e.upper().replace("-", "_") for e in edge_filter}
        active_types = allowed_edge_types & requested
        # Fallback: unknown filter values → use all allowed types rather than generating invalid Cypher
        if not active_types:
            active_types = allowed_edge_types
    else:
        active_types = allowed_edge_types

    edge_types_str = "|".join(sorted(active_types))

    # AGE Cypher - dual project_id predicate for GRAPH-04 isolation.
    # NODE_CAP shared with graph_traversal.py (200).
    cypher_body = (
        f"MATCH (seed:DomainPivot {{ioc_id: '{safe_ioc_id}', project_id: '{safe_pid}'}}) "
        f"MATCH (seed)-[:{edge_types_str}*1..{hops}]-(t) "
        f"WHERE t.project_id = '{safe_pid}' "
        f"RETURN properties(seed) AS sp, properties(t) AS tp "
        f"LIMIT {NODE_CAP}"
    )

    sql = (
        "SELECT * FROM cypher('intellibird_graph', $$ "
        + cypher_body
        + " $$) AS (sp ag_catalog.agtype, tp ag_catalog.agtype)"
    )

    nodes_by_id: dict[str, dict] = {}
    edge_tuples: list[tuple[str, str, str]] = []

    try:
        async with age_conn(db) as raw:
            rows = (await raw.exec_driver_sql(sql)).fetchall()
    except Exception as exc:
        log.error(
            "traverse_age_error",
            project_id=str(project_id),
            seed_ioc_id=str(seed_ioc_id),
            error=repr(exc),
        )
        raise HTTPException(status_code=503, detail="Graph traversal temporarily unavailable")

    if not rows:
        # Seed not found or no traversal results - return empty graph (not 404)
        return GraphResponse(nodes=[], edges=[], truncated=False)

    def _parse_agtype_props(val: object) -> dict:
        s = str(val)
        # Strip ::vertex or ::edge type annotation
        s = s.split("::")[0].strip()
        try:
            return json.loads(s)  # type: ignore[no-any-return]
        except Exception:
            return {}

    seed_props = _parse_agtype_props(rows[0][0])
    seed_node_id = seed_props.get("ioc_id") or safe_ioc_id
    seed_label = seed_props.get("domain") or seed_node_id
    nodes_by_id[seed_node_id] = {"id": seed_node_id, "label": seed_label, "type": "domain_pivot"}

    for row in rows:
        t_props = _parse_agtype_props(row[1])
        t_ioc_id = t_props.get("ioc_id")
        if not t_ioc_id:
            continue
        t_label = t_props.get("domain") or t_ioc_id
        nodes_by_id[t_ioc_id] = {"id": t_ioc_id, "label": t_label, "type": "domain_pivot"}
        edge_tuples.append((seed_node_id, t_ioc_id, "shares_infra"))

    truncated = len(rows) >= NODE_CAP

    # Build GraphResponse nodes + edges
    graph_nodes = [
        GraphNode(data=GraphNodeData(id=n["id"], label=n["label"], type=n["type"]))
        for n in nodes_by_id.values()
    ]
    graph_edges = [
        GraphEdge(data=GraphEdgeData(source=src, target=tgt, relation=rel))
        for src, tgt, rel in edge_tuples
    ]

    # Centrality computation - cached in Redis for 10 minutes
    redis = await get_redis()
    node_id_list = list(nodes_by_id.keys())
    centrality, centrality_truncated = await get_or_compute_centrality(
        redis, node_id_list, edge_tuples
    )

    log.info(
        "traverse_queried",
        project_id=str(project_id),
        seed_ioc_id=str(seed_ioc_id),
        hops=hops,
        node_count=len(graph_nodes),
        edge_count=len(graph_edges),
        truncated=truncated,
        centrality_computed=(centrality is not None),
    )

    return GraphResponse(
        nodes=graph_nodes,
        edges=graph_edges,
        truncated=truncated,
        per_node_centrality=centrality,
        centrality_truncated=centrality_truncated,
    )
