"""Cytoscape.js-compatible graph response schemas."""
from __future__ import annotations

from pydantic import BaseModel


class GraphNodeData(BaseModel):
    id: str
    label: str
    type: str
    tag_source: str | None = None
    centrality: float | None = None  # server-computed; None for non-traverse endpoints


class GraphNode(BaseModel):
    data: GraphNodeData


class GraphEdgeData(BaseModel):
    source: str
    target: str
    relation: str


class GraphEdge(BaseModel):
    data: GraphEdgeData


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool = False
    # Phase 28 centrality fields — only populated by the /traverse endpoint.
    # Existing endpoints (event graph, project graph) leave these at defaults.
    per_node_centrality: dict[str, float] | None = None
    centrality_truncated: bool = False
