"""Unit tests for classify_tier() pure function.

Covers SCR-05: tier classification at S/A/B/C/D boundaries and with custom cutoffs.
"""
from __future__ import annotations

from app.services.scoring import classify_tier


def test_classify_tier_boundaries() -> None:
    """classify_tier maps scores to correct tiers at each boundary value."""
    # S tier: score >= 90
    assert classify_tier(90.0) == "S"
    assert classify_tier(100.0) == "S"
    assert classify_tier(95.0) == "S"

    # A tier: 75 <= score < 90
    assert classify_tier(89.99) == "A"
    assert classify_tier(75.0) == "A"
    assert classify_tier(80.0) == "A"

    # B tier: 55 <= score < 75
    assert classify_tier(74.99) == "B"
    assert classify_tier(55.0) == "B"
    assert classify_tier(65.0) == "B"

    # C tier: 30 <= score < 55
    assert classify_tier(54.99) == "C"
    assert classify_tier(30.0) == "C"
    assert classify_tier(40.0) == "C"

    # D tier: score < 30
    assert classify_tier(29.99) == "D"
    assert classify_tier(0.0) == "D"
    assert classify_tier(10.0) == "D"


def test_classify_tier_custom_cutoffs() -> None:
    """classify_tier respects custom cutoff overrides."""
    custom = {"S": 95.0, "A": 80.0, "B": 60.0, "C": 40.0}

    assert classify_tier(95.0, cutoffs=custom) == "S"
    assert classify_tier(94.99, cutoffs=custom) == "A"
    assert classify_tier(85.0, cutoffs=custom) == "A"
    assert classify_tier(80.0, cutoffs=custom) == "A"
    assert classify_tier(79.99, cutoffs=custom) == "B"
    assert classify_tier(60.0, cutoffs=custom) == "B"
    assert classify_tier(59.99, cutoffs=custom) == "C"
    assert classify_tier(40.0, cutoffs=custom) == "C"
    assert classify_tier(39.99, cutoffs=custom) == "D"
    assert classify_tier(0.0, cutoffs=custom) == "D"


def test_classify_tier_none_cutoffs_uses_defaults() -> None:
    """Passing cutoffs=None falls back to DEFAULT_TIER_CUTOFFS."""
    # Explicit None should behave identically to omitting the arg.
    assert classify_tier(90.0, cutoffs=None) == "S"
    assert classify_tier(74.99, cutoffs=None) == "B"
    assert classify_tier(0.0, cutoffs=None) == "D"
