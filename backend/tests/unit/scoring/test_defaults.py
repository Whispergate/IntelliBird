"""Unit tests for DEFAULT_SCORING_CONFIG and ScoringWeights.

Covers SCR-02: bundled default scoring rules exist and have the correct shape.
"""
from __future__ import annotations

import pytest

from app.services.scoring import DEFAULT_SCORING_CONFIG, DEFAULT_TIER_CUTOFFS, ScoringWeights
from app.services.scoring.defaults import DEFAULT_SOURCE_CONFIDENCE


def test_default_scoring_config_shape() -> None:
    """DEFAULT_SCORING_CONFIG has all required top-level keys with correct values."""
    cfg = DEFAULT_SCORING_CONFIG

    # Required keys
    assert "weights" in cfg, "Missing 'weights' key"
    assert "decay_half_life_days" in cfg, "Missing 'decay_half_life_days' key"
    assert "tier_cutoffs" in cfg, "Missing 'tier_cutoffs' key"

    # Weight values and sum
    weights = cfg["weights"]
    assert set(weights.keys()) >= {"cvss", "recency", "source", "relevance"}
    weight_sum = sum(weights[k] for k in ("cvss", "recency", "source", "relevance"))
    assert weight_sum == 100, f"Weights must sum to 100, got {weight_sum}"

    # Locked default values (15-CONTEXT.md)
    assert weights["cvss"] == 50
    assert weights["recency"] == 20
    assert weights["source"] == 15
    assert weights["relevance"] == 15

    # Decay half-life
    assert cfg["decay_half_life_days"] == 14

    # Tier cutoffs — strictly descending S > A > B > C
    cutoffs = cfg["tier_cutoffs"]
    assert cutoffs["S"] > cutoffs["A"] > cutoffs["B"] > cutoffs["C"], (
        f"Tier cutoffs must be strictly descending: {cutoffs}"
    )
    # Locked default values
    assert cutoffs["S"] == 90
    assert cutoffs["A"] == 75
    assert cutoffs["B"] == 55
    assert cutoffs["C"] == 30


def test_scoring_weights_dataclass_defaults() -> None:
    """ScoringWeights() default instance has the locked values and validates sum."""
    w = ScoringWeights()
    assert w.cvss == 50.0
    assert w.recency == 20.0
    assert w.source == 15.0
    assert w.relevance == 15.0
    assert w.decay_half_life_days == 14.0


def test_scoring_weights_sum_validation() -> None:
    """ScoringWeights raises ValueError when weights do not sum to 100."""
    with pytest.raises(ValueError, match="sum to 100"):
        ScoringWeights(cvss=40.0, recency=20.0, source=15.0, relevance=15.0)


def test_scoring_weights_custom_valid() -> None:
    """ScoringWeights accepts custom weights that sum to 100."""
    w = ScoringWeights(cvss=40.0, recency=30.0, source=15.0, relevance=15.0)
    assert w.cvss == 40.0
    assert w.recency == 30.0


def test_default_tier_cutoffs_values() -> None:
    """DEFAULT_TIER_CUTOFFS has the locked S/A/B/C values."""
    assert DEFAULT_TIER_CUTOFFS["S"] == 90.0
    assert DEFAULT_TIER_CUTOFFS["A"] == 75.0
    assert DEFAULT_TIER_CUTOFFS["B"] == 55.0
    assert DEFAULT_TIER_CUTOFFS["C"] == 30.0


def test_default_source_confidence_values() -> None:
    """DEFAULT_SOURCE_CONFIDENCE has the locked per-feed-type confidence values."""
    assert DEFAULT_SOURCE_CONFIDENCE["taxii"] == 1.0
    assert DEFAULT_SOURCE_CONFIDENCE["nvd"] == 1.0
    assert DEFAULT_SOURCE_CONFIDENCE["rss_curated"] == 0.9
    assert DEFAULT_SOURCE_CONFIDENCE["rss"] == 0.7
