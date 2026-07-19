"""Depth-limited graph traversal for /events/{id}/graph endpoint.

M1 implementation: Python BFS over relational tables + raw_stix SROs.
AGE Cypher path deferred to M2 (see).

# AGE Cypher path deferred to M2 backlog (per RESEARCH §1). This module is
# SQLAlchemy multi-seed BFS through build_scope_predicate chokepoint.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.events import Event
from app.models.tags import AttackTechniqueTag

log = structlog.get_logger(__name__)

MIN_DEPTH = 1
MAX_DEPTH = 3
DEFAULT_DEPTH = 2
NODE_CAP = 200
EDGE_CAP = 1000  # default edge cap for per-event traversal (project uses 5000)

# STIX id prefix → node type mapping
_STIX_TYPE_TO_NODE_TYPE: dict[str, str] = {
    "threat-actor": "actor",
    "intrusion-set": "actor",
    "malware": "malware",
    "campaign": "campaign",
}


@dataclass
class GraphResult:
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    _node_ids: set[str] = field(default_factory=set)
    _edge_keys: set[tuple[str, str, str]] = field(default_factory=set)
    # Caps - callers that need different limits pass node_cap / edge_cap to __init__.
    # Defaults preserve existing per-event traverse_graph behaviour (NODE_CAP / EDGE_CAP).
    _node_cap: int = field(default=NODE_CAP)
    _edge_cap: int = field(default=EDGE_CAP)

    def __init__(
        self,
        node_cap: int = NODE_CAP,
        edge_cap: int = EDGE_CAP,
    ) -> None:
        self.nodes = []
        self.edges = []
        self.truncated = False
        self._node_ids = set()
        self._edge_keys = set()
        self._node_cap = node_cap
        self._edge_cap = edge_cap

    def add_node(self, node_id: str, label: str, node_type: str, tag_source: str | None = None) -> bool:
        """Return True if added (new), False if dedup hit."""
        if node_id in self._node_ids:
            return False
        self._node_ids.add(node_id)
        data: dict[str, Any] = {"id": node_id, "label": label, "type": node_type}
        if tag_source is not None:
            data["tag_source"] = tag_source
        self.nodes.append({"data": data})
        return True

    def add_edge(self, source: str, target: str, relation: str) -> bool:
        key = (source, target, relation)
        if key in self._edge_keys:
            return False
        self._edge_keys.add(key)
        self.edges.append({
            "data": {"source": source, "target": target, "relation": relation}
        })
        return True

    def at_cap(self) -> bool:
        return len(self.nodes) >= self._node_cap or len(self.edges) >= self._edge_cap


def _visibility_ok(ev_vis: str, dashboard_roles: list[str] | None) -> bool:
    """Visibility gating by dashboard_roles claim (AUTH-02 / C-2 closure).

    Empty / None list = unauthenticated (AUTH_ENABLED=false) or admin view -> pass through.
    """
    if not dashboard_roles:
        return True
    allowed: set[str] = {"shared"}
    if "red" in dashboard_roles:
        allowed.add("red_only")
    if "blue" in dashboard_roles:
        allowed.add("blue_only")
    return ev_vis in allowed


async def traverse_graph(
    session: AsyncSession,
    event_id: uuid.UUID,
    depth: int,
    dashboard_roles: list[str] | None = None,
    project_id: uuid.UUID | None = None,
) -> GraphResult | None:
    """BFS graph traversal from a seed event. Returns None if seed not found
 or visibility-excluded for the given dashboard_roles.

 kwarg (default None): project_id narrows traversal to events in the
 given project. When set:
   - Seed event must have seed.project_id == project_id (else return None)
   - Layer 3 cross-event expansion JOINs events with .where(project_id == X)
     so no event from another project can leak into the result (H-3 closure -
     never via AGE node properties).
   - Layers 1+2 are seed-scoped (no cross-event fetch) so no additional filter
     needed beyond the seed guard.

 Raises ValueError for invalid depth (router should catch and return 400).
"""
    if depth < MIN_DEPTH or depth > MAX_DEPTH:
        raise ValueError(f"depth must be {MIN_DEPTH}..{MAX_DEPTH}, got {depth}")

    # Load seed event (composite PK - use where)
    seed = (await session.execute(
        select(Event).where(Event.id == event_id)
    )).scalar_one_or_none()
    if seed is None or not _visibility_ok(seed.visibility, dashboard_roles):
        return None

    # PRJ-04 / H-3: seed must belong to the project when project_id
    # is set. Return None (indistinguishable from 'not found') to avoid
    # information disclosure across project boundaries.
    if project_id is not None and seed.project_id != project_id:
        return None

    result = GraphResult()
    seed_node_id = f"event:{seed.id}"
    result.add_node(seed_node_id, seed.title or str(seed.id), "event")

    # --- Layer 1: event → techniques --------------------------------------
    technique_ids: list[str] = []
    if depth >= 1:
        rows = (await session.execute(
            select(AttackTechniqueTag.technique_id, AttackTechniqueTag.tag_source).where(
                AttackTechniqueTag.event_id == event_id
            )
        )).all()
        for row in rows:
            tid, tag_source = row[0], row[1]
            technique_ids.append(tid)
            tech_node_id = f"technique:{tid}"
            result.add_node(tech_node_id, tid, "technique", tag_source=tag_source)
            result.add_edge(seed_node_id, tech_node_id, "uses")
            if result.at_cap():
                result.truncated = True
                log.info(
                    "graph_truncated",
                    event_id=str(event_id),
                    layer=1,
                    node_count=len(result.nodes),
                )
                return result

    # --- Layer 2: raw_stix SROs → actor / malware / campaign ---------------
    if depth >= 2:
        if seed.raw_stix is None:
            log.debug("graph_depth2_no_stix", event_id=str(event_id))
        else:
            objects = seed.raw_stix.get("objects") if isinstance(seed.raw_stix, dict) else None
            if objects:
                # First pass: collect stix_id → object dict for non-relationship objects
                by_stix_id: dict[str, dict[str, Any]] = {}
                for obj in objects:
                    if not isinstance(obj, dict):
                        continue
                    oid = obj.get("id")
                    otype = obj.get("type")
                    if isinstance(oid, str) and isinstance(otype, str):
                        by_stix_id[oid] = obj

                # Second pass: emit relationship nodes + edges
                for obj in objects:
                    if not isinstance(obj, dict):
                        continue
                    if obj.get("type") != "relationship":
                        continue
                    source_ref = obj.get("source_ref")
                    target_ref = obj.get("target_ref")
                    rel_type = obj.get("relationship_type", "related-to")
                    if not isinstance(source_ref, str) or not isinstance(target_ref, str):
                        continue

                    for ref in (source_ref, target_ref):
                        stix_kind = ref.split("--", 1)[0]
                        node_type = _STIX_TYPE_TO_NODE_TYPE.get(stix_kind)
                        if node_type is None:
                            continue  # skip non-displayable types
                        node_id = f"{node_type}:{ref}"
                        label = by_stix_id.get(ref, {}).get("name") or ref
                        result.add_node(node_id, label, node_type)
                        if result.at_cap():
                            result.truncated = True
                            log.info(
                                "graph_truncated",
                                event_id=str(event_id),
                                layer=2,
                                node_count=len(result.nodes),
                            )
                            return result

                    # Connect the two SRO ends if both are displayable node types
                    s_kind = source_ref.split("--", 1)[0]
                    t_kind = target_ref.split("--", 1)[0]
                    s_type = _STIX_TYPE_TO_NODE_TYPE.get(s_kind)
                    t_type = _STIX_TYPE_TO_NODE_TYPE.get(t_kind)
                    if s_type and t_type:
                        result.add_edge(
                            f"{s_type}:{source_ref}",
                            f"{t_type}:{target_ref}",
                            rel_type,
                        )
                    # Also tie each actor/malware/campaign back to the seed event
                    if s_type:
                        result.add_edge(
                            f"{s_type}:{source_ref}",
                            seed_node_id,
                            rel_type,
                        )
                    if t_type:
                        result.add_edge(
                            seed_node_id,
                            f"{t_type}:{target_ref}",
                            rel_type,
                        )

    # --- Layer 3: same-technique cross-events (per-event only; skipped in traverse_project) ------
    if depth >= 3 and technique_ids:
        cross_rows = (await session.execute(
            select(AttackTechniqueTag.event_id, AttackTechniqueTag.technique_id)
            .where(AttackTechniqueTag.technique_id.in_(technique_ids))
            .where(AttackTechniqueTag.event_id != event_id)
        )).all()
        if cross_rows:
            other_event_ids = list({r[0] for r in cross_rows})
            other_q = select(Event).where(Event.id.in_(other_event_ids))
            # PRJ-04 / H-3: every cross-event expansion hop must
            # re-apply the project filter via JOIN-to-events. This is the
            # enforcement point - seed-match at layer 0 is not sufficient.
            if project_id is not None:
                other_q = other_q.where(Event.project_id == project_id)
            other_events = (await session.execute(other_q)).scalars().all()
            events_by_id = {str(e.id): e for e in other_events}
            for ev_id, tid in cross_rows:
                ev = events_by_id.get(str(ev_id))
                if ev is None or not _visibility_ok(ev.visibility, dashboard_roles):
                    continue
                other_node_id = f"event:{ev.id}"
                result.add_node(other_node_id, ev.title or str(ev.id), "event")
                result.add_edge(other_node_id, f"technique:{tid}", "uses")
                if result.at_cap():
                    result.truncated = True
                    log.info(
                        "graph_truncated",
                        event_id=str(event_id),
                        layer=3,
                        node_count=len(result.nodes),
                    )
                    return result

    return result


# ---------------------------------------------------------------------------
# Project-aggregate multi-seed BFS (GRAPH-01 / GRAPH-02)
# ---------------------------------------------------------------------------

# AGE Cypher path deferred to M2 backlog (per RESEARCH §1). This is SQLAlchemy
# multi-seed BFS through build_scope_predicate chokepoint.


async def traverse_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    dashboard_roles: list[str] | None = None,
    max_nodes: int = 1000,
    max_edges: int = 5000,
) -> GraphResult:
    """Multi-seed BFS across all events in a project.

    Security guarantee: event collection flows through build_events_query with
    project_id kwarg which applies `Event.project_id == project_id` at the SQL
    layer. This is the same scope-predicate chokepoint used by the events list
    endpoint - cross-project leakage is structurally impossible.

    Layers traversed per seed event:
      - Layer 1: AttackTechniqueTag JOIN (techniques used by the event)
      - Layer 2: raw_stix SROs (actor / malware / campaign relationships)
    Layer 3 (same-technique cross-event expansion) is deliberately SKIPPED for
    multi-seed traversal: the seed set already spans all project events so Layer 3
    would be redundant and would double-count shared-technique links.

    Returns a GraphResult with truncated=True when max_nodes or max_edges is hit.
    """
    from app.services.events_query import EventsQueryParams, build_events_query

    # Step 1: collect event_ids scoped to this project via the chokepoint.
    # EventsQueryParams() with no filters = "all events" (subject to project_id scope).
    params = EventsQueryParams()
    stmt = build_events_query(params, dashboard_roles, project_id=project_id)
    event_ids: list[uuid.UUID] = list(
        (await session.execute(stmt.with_only_columns(Event.id))).scalars().all()
    )

    # Step 2: shared accumulator with caller-configurable caps.
    result = GraphResult(node_cap=max_nodes, edge_cap=max_edges)

    # Step 3: iterate seeds, accumulate Layer 1 + Layer 2 into shared result.
    for event_id in event_ids:
        # Load event row (needed for title + visibility + raw_stix).
        seed = (await session.execute(
            select(Event).where(Event.id == event_id)
        )).scalar_one_or_none()
        if seed is None or not _visibility_ok(seed.visibility, dashboard_roles):
            continue

        seed_node_id = f"event:{seed.id}"
        result.add_node(seed_node_id, seed.title or str(seed.id), "event")
        if result.at_cap():
            result.truncated = True
            log.info(
                "project_graph_truncated",
                project_id=str(project_id),
                layer="seed",
                node_count=len(result.nodes),
                edge_count=len(result.edges),
            )
            return result

        # --- Layer 1: event → techniques -----------------------------------
        rows = (await session.execute(
            select(AttackTechniqueTag.technique_id, AttackTechniqueTag.tag_source).where(
                AttackTechniqueTag.event_id == event_id
            )
        )).all()
        for row in rows:
            tid, tag_source = row[0], row[1]
            tech_node_id = f"technique:{tid}"
            result.add_node(tech_node_id, tid, "technique", tag_source=tag_source)
            result.add_edge(seed_node_id, tech_node_id, "uses")
            if result.at_cap():
                result.truncated = True
                log.info(
                    "project_graph_truncated",
                    project_id=str(project_id),
                    layer=1,
                    node_count=len(result.nodes),
                    edge_count=len(result.edges),
                )
                return result

        # --- Layer 2: raw_stix SROs → actor / malware / campaign -----------
        if seed.raw_stix is not None:
            objects = seed.raw_stix.get("objects") if isinstance(seed.raw_stix, dict) else None
            if objects:
                by_stix_id: dict[str, dict[str, Any]] = {}
                for obj in objects:
                    if not isinstance(obj, dict):
                        continue
                    oid = obj.get("id")
                    otype = obj.get("type")
                    if isinstance(oid, str) and isinstance(otype, str):
                        by_stix_id[oid] = obj

                for obj in objects:
                    if not isinstance(obj, dict):
                        continue
                    if obj.get("type") != "relationship":
                        continue
                    source_ref = obj.get("source_ref")
                    target_ref = obj.get("target_ref")
                    rel_type = obj.get("relationship_type", "related-to")
                    if not isinstance(source_ref, str) or not isinstance(target_ref, str):
                        continue

                    for ref in (source_ref, target_ref):
                        stix_kind = ref.split("--", 1)[0]
                        node_type = _STIX_TYPE_TO_NODE_TYPE.get(stix_kind)
                        if node_type is None:
                            continue
                        node_id = f"{node_type}:{ref}"
                        label = by_stix_id.get(ref, {}).get("name") or ref
                        result.add_node(node_id, label, node_type)
                        if result.at_cap():
                            result.truncated = True
                            log.info(
                                "project_graph_truncated",
                                project_id=str(project_id),
                                layer=2,
                                node_count=len(result.nodes),
                                edge_count=len(result.edges),
                            )
                            return result

                    s_kind = source_ref.split("--", 1)[0]
                    t_kind = target_ref.split("--", 1)[0]
                    s_type = _STIX_TYPE_TO_NODE_TYPE.get(s_kind)
                    t_type = _STIX_TYPE_TO_NODE_TYPE.get(t_kind)
                    if s_type and t_type:
                        result.add_edge(
                            f"{s_type}:{source_ref}",
                            f"{t_type}:{target_ref}",
                            rel_type,
                        )
                    if s_type:
                        result.add_edge(
                            f"{s_type}:{source_ref}",
                            seed_node_id,
                            rel_type,
                        )
                    if t_type:
                        result.add_edge(
                            seed_node_id,
                            f"{t_type}:{target_ref}",
                            rel_type,
                        )

        # Step 4: short-circuit the outer event loop when caps hit.
        if result.at_cap():
            result.truncated = True
            log.info(
                "project_graph_truncated",
                project_id=str(project_id),
                layer="post_event",
                node_count=len(result.nodes),
                edge_count=len(result.edges),
            )
            return result

    log.info(
        "project_graph_complete",
        project_id=str(project_id),
        event_count=len(event_ids),
        node_count=len(result.nodes),
        edge_count=len(result.edges),
        truncated=result.truncated,
    )
    return result
