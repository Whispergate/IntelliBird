"""graph_traversal tag_source propagation --03 target (MAP-03, MAP-04)."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from app.services.graph_traversal import GraphResult, traverse_graph


# ---------------------------------------------------------------------------
# GraphResult.add_node tag_source unit tests (no DB)
# ---------------------------------------------------------------------------

def test_add_node_stores_tag_source():
    """add_node with tag_source='analyst' stores it in node data dict."""
    result = GraphResult()
    result.add_node("technique:T1001", "T1001", "technique", tag_source="analyst")
    assert len(result.nodes) == 1
    assert result.nodes[0]["data"]["tag_source"] == "analyst"


def test_add_node_omits_tag_source_when_none():
    """add_node without tag_source (default None) must NOT include 'tag_source' key in data."""
    result = GraphResult()
    result.add_node("technique:T1001", "T1001", "technique")
    assert len(result.nodes) == 1
    assert "tag_source" not in result.nodes[0]["data"]


def test_add_node_omits_tag_source_explicit_none():
    """add_node with tag_source=None must NOT include 'tag_source' key in data."""
    result = GraphResult()
    result.add_node("technique:T1001", "T1001", "technique", tag_source=None)
    assert len(result.nodes) == 1
    assert "tag_source" not in result.nodes[0]["data"]


# ---------------------------------------------------------------------------
# traverse_graph integration test with mocked session
# ---------------------------------------------------------------------------

async def test_traverse_graph_includes_tag_source_on_techniques():
    """traverse_graph depth=1 should forward tag_source from AttackTechniqueTag to node data."""
    fake_event = MagicMock()
    eid = uuid.uuid4()
    fake_event.id = eid
    fake_event.visibility = "shared"
    fake_event.title = "Test Event"
    fake_event.raw_stix = None

    # Mock session.execute to return:
    # - first call: seed event
    # - second call: technique rows with (technique_id, tag_source) tuples
    seed_result = MagicMock()
    seed_result.scalar_one_or_none = MagicMock(return_value=fake_event)

    tech_result = MagicMock()
    # Two technique rows: (technique_id, tag_source)
    tech_result.all = MagicMock(return_value=[
        ("T1190", "analyst"),
        ("T1059", "feed_asserted"),
    ])

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[seed_result, tech_result])

    out = await traverse_graph(session, eid, depth=1, dashboard_roles=None)

    assert out is not None
    # 3 nodes: seed event + 2 techniques
    assert len(out.nodes) == 3

    # Find technique nodes
    tech_nodes = {n["data"]["id"]: n["data"] for n in out.nodes if n["data"]["type"] == "technique"}

    assert "technique:T1190" in tech_nodes
    assert tech_nodes["technique:T1190"]["tag_source"] == "analyst"

    assert "technique:T1059" in tech_nodes
    assert tech_nodes["technique:T1059"]["tag_source"] == "feed_asserted"
