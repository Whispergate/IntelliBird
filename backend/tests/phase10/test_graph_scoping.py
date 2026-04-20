"""test_graph_scoping — PRJ-04 (plan 10-05).

Graph BFS scoped by project_id via JOIN-to-events at every expansion step
(H-3 mitigation — never via AGE node properties). Asserts no cross-project
leakage, truncation cap honoured, shared-technique actors stay isolated.

Note: tag_source values are bounded by the tag_source_enum (backend/app/
models/tags.py): feed_asserted / analyst / auto. "manual" is NOT a valid
enum value — use "analyst" for operator-authored tags in these tests.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone

import pytest

from app.models.events import Event
from app.models.projects import Project
from app.models.tags import AttackTechniqueTag
from app.services.graph_traversal import traverse_graph

pytestmark = pytest.mark.integration


async def _proj(db_session, name: str) -> Project:
    p = Project(
        id=_uuid.uuid4(), name=name, engagement_type="internal",
        created_by="system",
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


async def _event(db_session, project: Project, title: str) -> Event:
    e = Event(
        id=_uuid.uuid4(),
        stix_type="report",
        observed_at=datetime.now(timezone.utc),
        content_hash=str(_uuid.uuid4()),
        visibility="shared",
        project_id=project.id,
        title=title,
        raw_stix={"objects": []},
    )
    db_session.add(e)
    await db_session.commit()
    await db_session.refresh(e)
    return e


@pytest.mark.asyncio
async def test_no_cross_project_leakage(db_session):
    """Event in Project A with technique T1566 shared with Project B:
    depth=3 graph seeded at A's event must NOT surface Project B's event.
    """
    a = await _proj(db_session, "A")
    b = await _proj(db_session, "B")
    e_a = await _event(db_session, a, "A seed")
    e_b = await _event(db_session, b, "B other")
    db_session.add_all([
        AttackTechniqueTag(event_id=e_a.id, technique_id="T1566", tag_source="analyst"),
        AttackTechniqueTag(event_id=e_b.id, technique_id="T1566", tag_source="analyst"),
    ])
    await db_session.commit()

    result = await traverse_graph(db_session, e_a.id, depth=3, project_id=a.id)
    assert result is not None
    node_event_ids = [
        n["data"]["id"] for n in result.nodes if n["data"]["type"] == "event"
    ]
    assert f"event:{e_a.id}" in node_event_ids
    assert f"event:{e_b.id}" not in node_event_ids


@pytest.mark.asyncio
async def test_truncation(db_session):
    """250 cross-events at the same technique -> truncate at NODE_CAP=200."""
    p = await _proj(db_session, "trunc")
    seed = await _event(db_session, p, "seed")
    db_session.add(AttackTechniqueTag(
        event_id=seed.id, technique_id="T1001", tag_source="analyst",
    ))
    await db_session.commit()

    # 250 cross-events at same technique -> BFS must truncate at NODE_CAP=200
    for i in range(250):
        ev = await _event(db_session, p, f"x{i}")
        db_session.add(AttackTechniqueTag(
            event_id=ev.id, technique_id="T1001", tag_source="analyst",
        ))
    await db_session.commit()

    result = await traverse_graph(db_session, seed.id, depth=3, project_id=p.id)
    assert result is not None
    assert result.truncated is True
    assert len(result.nodes) <= 200


@pytest.mark.asyncio
async def test_shared_technique_isolation(db_session):
    """Even if the seed has no same-technique siblings in its own project,
    traversal must NOT pull events from another project that share the technique.
    """
    a = await _proj(db_session, "A2")
    b = await _proj(db_session, "B2")
    seed = await _event(db_session, a, "A solo")
    # B has 2 events sharing the technique; A has 0 besides the seed
    e_b1 = await _event(db_session, b, "B1")
    e_b2 = await _event(db_session, b, "B2")
    db_session.add_all([
        AttackTechniqueTag(event_id=seed.id, technique_id="T1234", tag_source="analyst"),
        AttackTechniqueTag(event_id=e_b1.id, technique_id="T1234", tag_source="analyst"),
        AttackTechniqueTag(event_id=e_b2.id, technique_id="T1234", tag_source="analyst"),
    ])
    await db_session.commit()

    result = await traverse_graph(db_session, seed.id, depth=3, project_id=a.id)
    assert result is not None
    node_event_ids = {
        n["data"]["id"] for n in result.nodes if n["data"]["type"] == "event"
    }
    # Only the seed — no B leakage
    assert node_event_ids == {f"event:{seed.id}"}
