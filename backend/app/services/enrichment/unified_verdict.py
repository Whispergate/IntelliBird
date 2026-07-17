"""Unified verdict aggregation across enrichment providers — ENRICH-02.

Computes the worst-case verdict across all IOCEnrichment rows for a single
IOC. Severity ordering: malicious > suspicious > unknown > clean.

Public API:
  compute_unified_verdict(enrichments) -> VerdictType
"""
from __future__ import annotations

from app.schemas.enrichment import VerdictType

# ---------------------------------------------------------------------------
# Severity rank — higher = worse
# ---------------------------------------------------------------------------

VERDICT_RANK: dict[str, int] = {
    "malicious":  3,
    "suspicious": 2,
    "unknown":    1,
    "clean":      0,
}


def compute_unified_verdict(enrichments) -> VerdictType:
    """Return the highest-severity verdict across a list of enrichment rows.

    Args:
        enrichments: List of IOCEnrichment ORM objects (or any objects with
                     a `.verdict` attribute) or dicts with a "verdict" key.

    Returns:
        The worst-case VerdictType. Returns "unknown" for an empty list.
    """
    if not enrichments:
        return "unknown"

    best_rank = -1
    best_verdict: VerdictType = "unknown"

    for item in enrichments:
        # Support both ORM objects and plain dicts
        verdict = item.verdict if hasattr(item, "verdict") else item.get("verdict", "unknown")
        rank = VERDICT_RANK.get(verdict, 1)  # default "unknown" rank for unrecognised values
        if rank > best_rank:
            best_rank = rank
            best_verdict = verdict  # type: ignore[assignment]

    return best_verdict


__all__ = ["compute_unified_verdict", "VERDICT_RANK"]
