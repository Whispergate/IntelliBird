"""Unit tests for traverse_graph — depth cap, node cap, BFS behavior."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.graph_traversal import (
    DEFAULT_DEPTH,
    MAX_DEPTH,
    MIN_DEPTH,
    NODE_CAP,
    GraphResult,
    traverse_graph,
)


def test_depth_cap_constants():
    assert MIN_DEPTH == 1
    assert MAX_DEPTH == 3
    assert DEFAULT_DEPTH == 2
    assert NODE_CAP == 200


@pytest.mark.asyncio
async def test_depth_below_min_raises():
    session = AsyncMock()
    with pytest.raises(ValueError):
        await traverse_graph(session, uuid.uuid4(), depth=0)


@pytest.mark.asyncio
async def test_depth_above_max_raises():
    session = AsyncMock()
    with pytest.raises(ValueError):
        await traverse_graph(session, uuid.uuid4(), depth=4)


def test_graph_result_dedup_nodes():
    g = GraphResult()
    assert g.add_node("event:a", "A", "event") is True
    assert g.add_node("event:a", "A", "event") is False
    assert len(g.nodes) == 1


def test_graph_result_dedup_edges():
    g = GraphResult()
    assert g.add_edge("x", "y", "uses") is True
    assert g.add_edge("x", "y", "uses") is False
    assert len(g.edges) == 1
    # Different relation is a new edge
    assert g.add_edge("x", "y", "other") is True
    assert len(g.edges) == 2


def test_graph_result_at_cap():
    g = GraphResult()
    for i in range(NODE_CAP):
        g.add_node(f"event:{i}", str(i), "event")
    assert g.at_cap() is True


@pytest.mark.asyncio
async def test_seed_not_found_returns_none():
    """When session returns no seed event, traverse returns None."""
    session = AsyncMock()
    # First execute() call (seed select) returns scalar_one_or_none → None
    exec_result = MagicMock()
    exec_result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute.return_value = exec_result
    out = await traverse_graph(session, uuid.uuid4(), depth=2)
    assert out is None


@pytest.mark.asyncio
async def test_visibility_red_excludes_blue_only_seed():
    """Seed marked blue_only → red role gets None."""
    session = AsyncMock()
    fake_event = MagicMock()
    fake_event.id = uuid.uuid4()
    fake_event.visibility = "blue_only"
    fake_event.title = "X"
    fake_event.raw_stix = None
    exec_result = MagicMock()
    exec_result.scalar_one_or_none = MagicMock(return_value=fake_event)
    session.execute.return_value = exec_result
    out = await traverse_graph(session, fake_event.id, depth=1, role="red")
    assert out is None


@pytest.mark.asyncio
async def test_raw_stix_none_no_error_at_depth_2():
    """Seed with raw_stix=None and no techniques completes cleanly at depth 2."""
    session = AsyncMock()
    fake_event = MagicMock()
    fake_event.id = uuid.uuid4()
    fake_event.visibility = "shared"
    fake_event.title = "Event X"
    fake_event.raw_stix = None

    # Two execute calls: (1) seed select, (2) techniques select (empty)
    seed_result = MagicMock()
    seed_result.scalar_one_or_none = MagicMock(return_value=fake_event)
    tech_result = MagicMock()
    tech_result.all = MagicMock(return_value=[])

    session.execute = AsyncMock(side_effect=[seed_result, tech_result])
    out = await traverse_graph(session, fake_event.id, depth=2, role=None)
    assert out is not None
    assert len(out.nodes) == 1  # only seed event node
    assert out.truncated is False


def test_node_id_format():
    g = GraphResult()
    g.add_node("event:abc-123", "E", "event")
    g.add_node("technique:T1190", "T", "technique")
    g.add_node("actor:threat-actor--xxx", "A", "actor")
    ids = {n["data"]["id"] for n in g.nodes}
    assert "event:abc-123" in ids
    assert "technique:T1190" in ids
    assert "actor:threat-actor--xxx" in ids


@pytest.mark.asyncio
async def test_visibility_blue_excludes_red_only_seed():
    """Seed marked red_only → blue role gets None."""
    session = AsyncMock()
    fake_event = MagicMock()
    fake_event.id = uuid.uuid4()
    fake_event.visibility = "red_only"
    fake_event.title = "RedOp"
    fake_event.raw_stix = None
    exec_result = MagicMock()
    exec_result.scalar_one_or_none = MagicMock(return_value=fake_event)
    session.execute.return_value = exec_result
    out = await traverse_graph(session, fake_event.id, depth=1, role="blue")
    assert out is None


@pytest.mark.asyncio
async def test_depth_1_only_adds_seed_node_when_no_techniques():
    """depth=1 with no technique tags → only seed event node, no edges."""
    session = AsyncMock()
    fake_event = MagicMock()
    fake_event.id = uuid.uuid4()
    fake_event.visibility = "shared"
    fake_event.title = "Seed"
    fake_event.raw_stix = None

    seed_result = MagicMock()
    seed_result.scalar_one_or_none = MagicMock(return_value=fake_event)
    tech_result = MagicMock()
    tech_result.all = MagicMock(return_value=[])

    session.execute = AsyncMock(side_effect=[seed_result, tech_result])
    out = await traverse_graph(session, fake_event.id, depth=1, role=None)
    assert out is not None
    assert len(out.nodes) == 1
    assert len(out.edges) == 0
    assert out.nodes[0]["data"]["type"] == "event"


@pytest.mark.asyncio
async def test_depth_1_adds_technique_nodes():
    """depth=1 with one technique tag → seed + technique nodes + 'uses' edge."""
    session = AsyncMock()
    fake_event = MagicMock()
    eid = uuid.uuid4()
    fake_event.id = eid
    fake_event.visibility = "shared"
    fake_event.title = "CVE Event"
    fake_event.raw_stix = None

    seed_result = MagicMock()
    seed_result.scalar_one_or_none = MagicMock(return_value=fake_event)
    tech_result = MagicMock()
    tech_result.all = MagicMock(return_value=[("T1190", "feed_asserted")])

    session.execute = AsyncMock(side_effect=[seed_result, tech_result])
    out = await traverse_graph(session, eid, depth=1, role=None)
    assert out is not None
    assert len(out.nodes) == 2
    ids = {n["data"]["id"] for n in out.nodes}
    assert f"event:{eid}" in ids
    assert "technique:T1190" in ids
    assert len(out.edges) == 1
    assert out.edges[0]["data"]["relation"] == "uses"


def test_node_cap_truncate():
    """Adding NODE_CAP nodes should set truncated flag via at_cap."""
    g = GraphResult()
    for i in range(NODE_CAP - 1):
        g.add_node(f"event:{i}", str(i), "event")
    assert g.at_cap() is False
    g.add_node(f"event:{NODE_CAP - 1}", "last", "event")
    assert g.at_cap() is True


@pytest.mark.asyncio
async def test_depth_exact_min_valid():
    """depth=1 (MIN_DEPTH) must not raise ValueError."""
    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute.return_value = exec_result
    # Should return None (seed not found), not raise
    out = await traverse_graph(session, uuid.uuid4(), depth=MIN_DEPTH)
    assert out is None


@pytest.mark.asyncio
async def test_depth_exact_max_valid():
    """depth=3 (MAX_DEPTH) must not raise ValueError."""
    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute.return_value = exec_result
    out = await traverse_graph(session, uuid.uuid4(), depth=MAX_DEPTH)
    assert out is None
