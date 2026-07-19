"""Server-side graph centrality computation - GRAPH-03.

Computes PageRank + betweenness centrality via networkx for graphs returned
by the traverse endpoint. Results are cached in Redis for 10 minutes keyed
by the sorted set of node IDs (SHA-256).

Skip threshold: graphs with > 500 nodes skip computation (too slow for p95
latency budget). Client falls back to uniform node sizing.
"""
from __future__ import annotations

import hashlib
import json
import logging

import networkx as nx

logger = logging.getLogger(__name__)

_CENTRALITY_NODE_LIMIT = 500
_CENTRALITY_CACHE_TTL = 600  # 10 minutes


def _cache_key(node_ids: list[str]) -> str:
    h = hashlib.sha256(json.dumps(sorted(node_ids)).encode()).hexdigest()
    return f"graph:centrality:{h}"


def _compute(node_ids: list[str], edge_tuples: list[tuple[str, str, str]]) -> dict[str, float] | None:
    """Pure computation - no I/O. Returns None if > 500 nodes."""
    if len(node_ids) > _CENTRALITY_NODE_LIMIT:
        return None

    G = nx.DiGraph()
    G.add_nodes_from(node_ids)
    for src, tgt, etype in edge_tuples:
        G.add_edge(src, tgt, edge_type=etype)

    if len(G.nodes) == 0:
        return {}

    pr = nx.pagerank(G, alpha=0.85)
    bc = nx.betweenness_centrality(G, normalized=True)

    all_nodes = set(pr.keys()) | set(bc.keys())
    combined = {n: (pr.get(n, 0.0) + bc.get(n, 0.0)) / 2.0 for n in all_nodes}
    max_score = max(combined.values()) if combined else 1.0
    if max_score == 0:
        return {k: 0.0 for k in combined}
    return {k: v / max_score for k, v in combined.items()}


async def get_or_compute_centrality(
    redis,
    node_ids: list[str],
    edge_tuples: list[tuple[str, str, str]],
) -> tuple[dict[str, float] | None, bool]:
    """Return (centrality_dict, centrality_truncated).

    centrality_dict is None when graph exceeds 500 nodes.
    centrality_truncated=True in that case.
    Results are cached in Redis for 10 minutes.
    """
    if len(node_ids) > _CENTRALITY_NODE_LIMIT:
        return None, True

    key = _cache_key(node_ids)
    cached = await redis.get(key)
    if cached:
        return json.loads(cached), False

    scores = _compute(node_ids, edge_tuples)
    if scores is not None:
        await redis.set(key, json.dumps(scores), ex=_CENTRALITY_CACHE_TTL)

    return scores, False
