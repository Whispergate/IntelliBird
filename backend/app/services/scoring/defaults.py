"""Bundled default scoring configuration.

DEFAULT_SCORING_CONFIG mirrors the JSONB shape stored in
``project_scoring_rules.rules`` — projects with NULL/empty JSONB rules
fall through to these values.

Locked in 15-CONTEXT.md:
    - weights: cvss=50 / recency=20 / source=15 / relevance=15  (sum=100)
    - decay_half_life_days: 14
    - tier_cutoffs: S>=90, A>=75, B>=55, C>=30, D<30
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoringWeights:
    """Immutable scoring weight configuration.

    All four component weights (cvss + recency + source + relevance) must sum
    to exactly 100.0 (±0.001 tolerance for float arithmetic).
    """

    cvss: float = 50.0
    recency: float = 20.0
    source: float = 15.0
    relevance: float = 15.0
    decay_half_life_days: float = 14.0

    def __post_init__(self) -> None:
        weight_sum = self.cvss + self.recency + self.source + self.relevance
        if abs(weight_sum - 100.0) > 0.001:
            raise ValueError(
                f"ScoringWeights cvss+recency+source+relevance must sum to 100.0, "
                f"got {weight_sum:.4f}"
            )


# Default tier cutoffs — per-project overridable via project_scoring_rules JSONB.
# D tier is implicit: score < C cutoff.
DEFAULT_TIER_CUTOFFS: dict[str, float] = {
    "S": 90.0,
    "A": 75.0,
    "B": 55.0,
    "C": 30.0,
}

# DEFAULT_SCORING_CONFIG — mirrors JSONB shape in project_scoring_rules.rules.
# Used by operator docs, admin UI defaults, and backfill logic.
DEFAULT_SCORING_CONFIG: dict = {
    "weights": {
        "cvss": 50,
        "recency": 20,
        "source": 15,
        "relevance": 15,
    },
    "decay_half_life_days": 14,
    "tier_cutoffs": {
        "S": 90,
        "A": 75,
        "B": 55,
        "C": 30,
    },
}

# Source confidence defaults by feed_type.
# Operator can override per-source via source detail UI (confidence column on sources).
# Migration 013 backfill uses 'rss' = 0.7.
# 'rss_curated' (NCSC, CISA etc.) is an operator-set override — use 0.9 when a source
# has been manually elevated; the ingest default remains 0.7 for all RSS sources.
DEFAULT_SOURCE_CONFIDENCE: dict[str, float] = {
    "taxii": 1.0,
    "nvd": 1.0,
    "rss_curated": 0.9,
    "rss": 0.7,
}
