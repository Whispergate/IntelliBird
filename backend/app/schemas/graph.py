"""Cytoscape.js-compatible graph response schemas (D-29)."""
from __future__ import annotations

from pydantic import BaseModel


class GraphNodeData(BaseModel):
    id: str
    label: str
    type: str
    tag_source: str | None = None


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
