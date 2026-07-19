"""Tier classification - pure function. No DB, no I/O.

Locked cutoffs in 15-CONTEXT.md:
    S >= 90, A 75–89, B 55–74, C 30–54, D < 30

Cutoffs are per-project overridable via ``project_scoring_rules`` JSONB.
Custom cutoffs are passed as an optional ``cutoffs`` argument.
"""
from __future__ import annotations

from .defaults import DEFAULT_TIER_CUTOFFS

# TIER_RANGES provides closed (lo, hi) ranges for each tier.
# Used by plan 15-05 for the tier filter SQL WHERE clause.
# Note: D hi is 29.99 (not 30) - inclusive upper bound for SQL range queries.
TIER_RANGES: dict[str, tuple[float, float]] = {
    "S": (90.0, 100.0),
    "A": (75.0, 89.99),
    "B": (55.0, 74.99),
    "C": (30.0, 54.99),
    "D": (0.0, 29.99),
}


def classify_tier(
    score: float,
    cutoffs: dict[str, float] | None = None,
) -> str:
    """Map a 0–100 score to an S/A/B/C/D tier string.

    Args:
        score:   Numeric score in [0.0, 100.0].
        cutoffs: Optional override dict with keys "S", "A", "B", "C".
                 Falls back to ``DEFAULT_TIER_CUTOFFS`` if not supplied.

    Returns:
        One of ``"S"``, ``"A"``, ``"B"``, ``"C"``, ``"D"``.
    """
    c = cutoffs if cutoffs is not None else DEFAULT_TIER_CUTOFFS
    if score >= c["S"]:
        return "S"
    if score >= c["A"]:
        return "A"
    if score >= c["B"]:
        return "B"
    if score >= c["C"]:
        return "C"
    return "D"
