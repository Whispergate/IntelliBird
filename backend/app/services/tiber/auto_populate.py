"""TIBER report auto-populate functions - TIBER-04.

Four section fillers for the TIBER TTIR auto-populate flow:
  populate_threat_landscape      - top-N scored events from project scope
  populate_actor_profiles        - actor nodes via graph_traversal scoped to project
  populate_scenarios_longlist    - TTPs seen in project events, up to max_count
  populate_actionable_intelligence - scope summary + top 3 high-tier events

H-4 CHOKEPOINT ENFORCEMENT - MANDATORY:
  Every function MUST start with:
    scope_rows = await fetch_scope_rows_intel(db, project_id)
    predicate = build_scope_predicate(scope_rows)
  and pass `predicate` to all event queries.

  OR use graph_traversal.traverse_graph(project_id=project_id) which already
  enforces the project_id scope gate internally.

  These chokepoints are validated by PROD-01 leakage tests:
    test_tiber_threat_landscape_no_leakage
    test_tiber_actor_profiles_no_leakage
    test_tiber_scenarios_longlist_no_leakage

DEFENSIVE ASSERTION:
  Each function that returns Event rows includes an assert before return:
    assert all(str(r.project_id) == str(project_id) for r in rows)
  This is a belt-and-suspenders guard; the predicate is the primary enforcement.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.events import Event
from app.models.tags import AttackTechniqueTag
from app.services.project_scope import build_scope_predicate, fetch_scope_rows_intel


# ---------------------------------------------------------------------------
# Return types
# ---------------------------------------------------------------------------


@dataclass
class ActorProfileResult:
    """Populated actor profile from graph traversal, scoped to a project."""

    name: str
    motivation: str
    capability_assessment: str
    relevance_to_target: str
    source_event_ids: list[str] = field(default_factory=list)


@dataclass
class ScenarioLonglistEntry:
    """One candidate scenario row for the TIBER scenarios longlist."""

    actor_id: uuid.UUID | None
    attack_technique_id: str
    candidate_procedure_text: str


@dataclass
class ActionableIntelligenceResult:
    """Actionable intelligence section auto-populated data."""

    summary_text: str
    top_3_high_tier_events: list[dict[str, Any]]
    scope_rows_summary: dict[str, int]


# ---------------------------------------------------------------------------
# Populate threat landscape - H-4 chokepoint: build_scope_predicate
# ---------------------------------------------------------------------------


async def populate_threat_landscape(
    db: AsyncSession,
    project_id: uuid.UUID,
    top_n: int = 20,
) -> list[Event]:
    """Return top-N scored events for the Threat Landscape section.

    Scoped to project_id via build_scope_predicate (H-4 chokepoint).
    Events are ordered by score DESC NULLS LAST, then observed_at DESC.
    Returns a list of Event ORM objects - all rows have project_id == project_id.

    Args:
        db: Async SQLAlchemy session.
        project_id: The project to scope queries to.
        top_n: Maximum number of events to return (default 20).

    Returns:
        List of Event objects, all with .project_id == project_id.
    """
    # H-4 chokepoint: scope_rows → build_scope_predicate
    scope_rows = await fetch_scope_rows_intel(db, project_id)
    predicate = build_scope_predicate(scope_rows)

    stmt = (
        select(Event)
        .where(Event.project_id == project_id)
        .where(predicate)
        .order_by(
            Event.score.desc().nulls_last(),
            Event.observed_at.desc(),
            Event.id.desc(),
        )
        .limit(top_n)
    )
    rows = list((await db.execute(stmt)).scalars().all())

    # Defensive assertion - belt-and-suspenders beyond the predicate
    assert all(
        str(r.project_id) == str(project_id) for r in rows
    ), (
        f"populate_threat_landscape: leakage detected - "
        f"rows with wrong project_id: "
        f"{[str(r.project_id) for r in rows if str(r.project_id) != str(project_id)]}"
    )
    return rows


# ---------------------------------------------------------------------------
# Populate actor profiles - H-4 chokepoint: graph_traversal (project_id scoped)
# ---------------------------------------------------------------------------


async def populate_actor_profiles(
    db: AsyncSession,
    project_id: uuid.UUID,
    top_n: int = 6,
) -> list[ActorProfileResult]:
    """Return up to top_n actor profiles derived from the project's event graph.

    Uses graph_traversal.traverse_graph which internally scopes all BFS hops to
    project_id - the traverse_graph function enforces H-3 / PROD-01 project_id
    boundary at every layer (seed guard + Layer 3 cross-event WHERE clause).

    Because M1 graph_traversal is a BFS over relational tables (AGE Cypher deferred
    to M2), we derive actor profiles from events in the project that carry STIX
    relationship objects referencing threat-actor / intrusion-set nodes.

    The source_event_ids list on each ActorProfileResult contains only event IDs
    from project_id - never from another project (H-4 enforcement via scope predicate).

    Args:
        db: Async SQLAlchemy session.
        project_id: The project to scope queries to.
        top_n: Maximum number of actor profiles to return.

    Returns:
        List of ActorProfileResult dataclasses.
    """
    # H-4 chokepoint: scope events to project_id via build_scope_predicate
    scope_rows = await fetch_scope_rows_intel(db, project_id)
    predicate = build_scope_predicate(scope_rows)

    # Fetch project-scoped events that contain STIX relationship objects
    stmt = (
        select(Event)
        .where(Event.project_id == project_id)
        .where(predicate)
        .where(Event.raw_stix.isnot(None))
        .order_by(Event.observed_at.desc())
        .limit(200)  # scan enough events to find actor data
    )
    events = list((await db.execute(stmt)).scalars().all())

    # Defensive assertion
    assert all(
        str(e.project_id) == str(project_id) for e in events
    ), "populate_actor_profiles: event scope leakage detected"

    # Extract actor nodes from raw_stix SROs - mirrors graph_traversal Layer 2 logic
    _ACTOR_STIX_TYPES = {"threat-actor", "intrusion-set"}
    actors_seen: dict[str, dict] = {}  # stix_id → {name, event_ids}

    for event in events:
        if not isinstance(event.raw_stix, dict):
            continue
        objects = event.raw_stix.get("objects") or []
        # Build lookup map
        {
            obj["id"]: obj
            for obj in objects
            if isinstance(obj, dict) and "id" in obj and "type" in obj
        }
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            stix_type = obj.get("type", "")
            stix_id = obj.get("id", "")
            if stix_type in _ACTOR_STIX_TYPES and stix_id:
                if stix_id not in actors_seen:
                    actors_seen[stix_id] = {
                        "name": obj.get("name") or stix_id,
                        "motivation": _extract_motivation(obj),
                        "event_ids": [],
                    }
                actors_seen[stix_id]["event_ids"].append(str(event.id))

    # Sort by event count (relevance) descending, take top_n
    sorted_actors = sorted(
        actors_seen.values(),
        key=lambda a: len(a["event_ids"]),
        reverse=True,
    )[:top_n]

    return [
        ActorProfileResult(
            name=a["name"],
            motivation=a["motivation"],
            capability_assessment="",  # analyst-editable after auto-populate
            relevance_to_target="",
            source_event_ids=a["event_ids"],
        )
        for a in sorted_actors
    ]


def _extract_motivation(stix_obj: dict) -> str:
    """Extract motivation from a STIX ThreatActor or IntrusionSet object."""
    # STIX ThreatActor: primary_motivation field
    m = stix_obj.get("primary_motivation") or ""
    if not m:
        # IntrusionSet: goals field
        goals = stix_obj.get("goals") or []
        if isinstance(goals, list):
            m = ", ".join(goals[:2])
    return m or ""


# ---------------------------------------------------------------------------
# Populate scenarios longlist - H-4 chokepoint: build_scope_predicate
# ---------------------------------------------------------------------------


async def populate_scenarios_longlist(
    db: AsyncSession,
    project_id: uuid.UUID,
    max_count: int = 6,
) -> list[ScenarioLonglistEntry]:
    """Return up to max_count candidate scenarios from project-scoped TTPs.

    Derives the longlist by finding ATT&CK technique IDs that appear in events
    scoped to project_id (via build_scope_predicate). Each unique technique
    becomes a candidate scenario chain entry.

    H-4 chokepoint: events are filtered by project_id AND build_scope_predicate
    before joining to event_attack_techniques.

    Args:
        db: Async SQLAlchemy session.
        project_id: The project to scope queries to.
        max_count: Maximum number of candidate scenarios (default 6, ECB max).

    Returns:
        List of ScenarioLonglistEntry dataclasses, one per unique technique.
    """
    # H-4 chokepoint: scope_rows → build_scope_predicate
    scope_rows = await fetch_scope_rows_intel(db, project_id)
    predicate = build_scope_predicate(scope_rows)

    # Find events in scope, join to attack techniques, group by technique
    # Use a subquery to apply the scope predicate to events before joining
    scoped_event_ids_stmt = (
        select(Event.id)
        .where(Event.project_id == project_id)
        .where(predicate)
    )

    technique_counts_stmt = (
        select(
            AttackTechniqueTag.technique_id,
            sa.func.count(AttackTechniqueTag.event_id).label("event_count"),
        )
        .where(AttackTechniqueTag.event_id.in_(scoped_event_ids_stmt))
        .group_by(AttackTechniqueTag.technique_id)
        .order_by(sa.func.count(AttackTechniqueTag.event_id).desc())
        .limit(max_count)
    )

    rows = (await db.execute(technique_counts_stmt)).all()

    return [
        ScenarioLonglistEntry(
            actor_id=None,
            attack_technique_id=row[0],
            candidate_procedure_text="",
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Populate actionable intelligence - H-4 chokepoint: build_scope_predicate
# ---------------------------------------------------------------------------


async def populate_actionable_intelligence(
    db: AsyncSession,
    project_id: uuid.UUID,
) -> ActionableIntelligenceResult:
    """Return auto-populated Actionable Intelligence Assessment data.

    Fetches:
    - Top 3 high-tier (score >= 80.0, S/A tier) events from project scope
    - Summary of scope_rows by type (count per scope_type)
    - A generated summary text string

    H-4 chokepoint: scope_rows → build_scope_predicate.

    Args:
        db: Async SQLAlchemy session.
        project_id: The project to scope queries to.

    Returns:
        ActionableIntelligenceResult dataclass.
    """
    # H-4 chokepoint: scope_rows → build_scope_predicate
    scope_rows = await fetch_scope_rows_intel(db, project_id)
    predicate = build_scope_predicate(scope_rows)

    # Top 3 high-tier events (score >= 80.0 → S or A tier)
    HIGH_TIER_THRESHOLD = 80.0
    high_tier_stmt = (
        select(Event)
        .where(Event.project_id == project_id)
        .where(predicate)
        .where(Event.score >= HIGH_TIER_THRESHOLD)
        .order_by(Event.score.desc().nulls_last(), Event.observed_at.desc())
        .limit(3)
    )
    high_tier_events = list((await db.execute(high_tier_stmt)).scalars().all())

    # Defensive assertion
    assert all(
        str(e.project_id) == str(project_id) for e in high_tier_events
    ), "populate_actionable_intelligence: event scope leakage detected"

    # Summarise scope_rows by type
    scope_rows_summary: dict[str, int] = {}
    for row in scope_rows:
        scope_rows_summary[row.scope_type] = scope_rows_summary.get(row.scope_type, 0) + 1

    # Build summary text
    total_scope_rules = len(scope_rows)
    high_count = len(high_tier_events)
    summary_text = (
        f"Project scope contains {total_scope_rules} intelligence scope rule(s) "
        f"across {len(scope_rows_summary)} type(s). "
        f"{high_count} high-priority event(s) identified in the current scope. "
        "Review the top events below and update analyst recommendations accordingly."
    )

    top_3_dicts = [
        {
            "id": str(e.id),
            "title": e.title or "",
            "score": float(e.score) if e.score is not None else None,
            "stix_type": e.stix_type or "",
            "observed_at": e.observed_at.isoformat() if e.observed_at else None,
        }
        for e in high_tier_events
    ]

    return ActionableIntelligenceResult(
        summary_text=summary_text,
        top_3_high_tier_events=top_3_dicts,
        scope_rows_summary=scope_rows_summary,
    )
