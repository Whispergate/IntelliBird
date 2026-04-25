"""Unit tests for score_event() pure scoring function.

Covers SCR-01: composite formula, clamping, synthetic CVSS by feed_type,
and deterministic decay via injectable ``now`` kwarg.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.services.scoring import ScoringWeights, score_event


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXED_DT = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
DEFAULT_WEIGHTS = ScoringWeights()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_score_event_smoke() -> None:
    """Smoke test: a mid-range NVD event scored 7 days ago lands in the 60–90 range."""
    now = FIXED_DT
    observed = now - timedelta(days=7)

    score, scored_at, version = score_event(
        feed_type="nvd",
        cvss_score=7.5,
        observed_at=observed,
        source_confidence=1.0,
        tag_relevance=1.0,
        weights=DEFAULT_WEIGHTS,
        now=now,
    )

    assert 60.0 < score < 90.0, f"Expected score in (60, 90), got {score}"
    assert scored_at == now
    assert version == 1


def test_score_clamp() -> None:
    """score_event output is clamped to [0.0, 100.0] in both directions."""
    now = FIXED_DT

    # All-max signals: should approach 100 but never exceed it.
    score_max, _, _ = score_event(
        feed_type="taxii",
        cvss_score=10.0,
        observed_at=now,
        source_confidence=1.0,
        tag_relevance=1.0,
        weights=DEFAULT_WEIGHTS,
        now=now,
    )
    assert score_max <= 100.0, f"Max score exceeded 100: {score_max}"
    assert score_max > 95.0, f"All-max score too low: {score_max}"

    # All-zero signals: should be exactly 0.0.
    score_min, _, _ = score_event(
        feed_type="rss",
        cvss_score=0.0,
        observed_at=now - timedelta(days=365),
        source_confidence=0.0,
        tag_relevance=0.0,
        weights=DEFAULT_WEIGHTS,
        now=now,
    )
    assert score_min >= 0.0, f"Score went below 0: {score_min}"


def test_synthetic_cvss() -> None:
    """score_event synthesises a CVSS when cvss_score is None.

    - feed_type='rss' with cvss_score=None should give the same score as
      cvss_score=5.0 (rss synthetic = 5.0).
    - feed_type='taxii' synthetic = 6.0.
    - brand_severity='high' overrides feed_type and uses 8.0.
    """
    now = FIXED_DT
    common = dict(
        observed_at=now,
        source_confidence=0.8,
        tag_relevance=0.5,
        weights=DEFAULT_WEIGHTS,
        now=now,
    )

    # RSS synthetic = 5.0
    score_rss_none, _, _ = score_event(feed_type="rss", cvss_score=None, **common)
    score_rss_explicit, _, _ = score_event(feed_type="rss", cvss_score=5.0, **common)
    assert math.isclose(score_rss_none, score_rss_explicit, abs_tol=1e-6), (
        f"RSS synthetic mismatch: {score_rss_none} vs {score_rss_explicit}"
    )

    # TAXII synthetic = 6.0
    score_taxii_none, _, _ = score_event(feed_type="taxii", cvss_score=None, **common)
    score_taxii_explicit, _, _ = score_event(feed_type="taxii", cvss_score=6.0, **common)
    assert math.isclose(score_taxii_none, score_taxii_explicit, abs_tol=1e-6), (
        f"TAXII synthetic mismatch: {score_taxii_none} vs {score_taxii_explicit}"
    )

    # brand_severity='high' overrides feed_type (high → 8.0, regardless of feed_type)
    score_brand_high, _, _ = score_event(
        feed_type="rss",
        cvss_score=None,
        brand_severity="high",
        **common,
    )
    score_explicit_8, _, _ = score_event(feed_type="rss", cvss_score=8.0, **common)
    assert math.isclose(score_brand_high, score_explicit_8, abs_tol=1e-6), (
        f"brand_severity='high' should map to 8.0: {score_brand_high} vs {score_explicit_8}"
    )


def test_decay_injectable() -> None:
    """Decay factor halves every 14 days when using injectable now clock.

    Verifies the half-life formula: recency_factor = 2^(-age_days / 14).
    At age 0 days  → recency_factor = 1.0
    At age 14 days → recency_factor = 0.5
    At age 28 days → recency_factor = 0.25
    """
    base_dt = FIXED_DT

    # Construct weights that isolate the recency component for inspection:
    # set source and relevance to 0, use a minimal cvss so recency dominates.
    # With default weights: recency component = 20 * recency_factor.
    weights = DEFAULT_WEIGHTS

    # At age 0: recency_factor = 1.0, recency component = 20.0
    score_0, _, _ = score_event(
        feed_type="nvd",
        cvss_score=0.0,
        observed_at=base_dt,
        source_confidence=0.0,
        tag_relevance=0.0,
        weights=weights,
        now=base_dt,
    )
    # Only recency contributes: 20 * 1.0 = 20.0
    assert math.isclose(score_0, 20.0, abs_tol=1e-6), f"At age 0, expected 20.0, got {score_0}"

    # At age 14 days: recency_factor = 0.5, recency component = 10.0
    score_14, _, _ = score_event(
        feed_type="nvd",
        cvss_score=0.0,
        observed_at=base_dt,
        source_confidence=0.0,
        tag_relevance=0.0,
        weights=weights,
        now=base_dt + timedelta(days=14),
    )
    assert math.isclose(score_14, 10.0, abs_tol=1e-6), f"At age 14d, expected 10.0, got {score_14}"

    # At age 28 days: recency_factor = 0.25, recency component = 5.0
    score_28, _, _ = score_event(
        feed_type="nvd",
        cvss_score=0.0,
        observed_at=base_dt,
        source_confidence=0.0,
        tag_relevance=0.0,
        weights=weights,
        now=base_dt + timedelta(days=28),
    )
    assert math.isclose(score_28, 5.0, abs_tol=1e-6), f"At age 28d, expected 5.0, got {score_28}"


def test_future_dated_event_no_negative_age() -> None:
    """Future-dated events (feed clock skew) should not produce negative age."""
    now = FIXED_DT
    future_observed = now + timedelta(hours=6)  # 6h in the future

    score, _, _ = score_event(
        feed_type="rss",
        cvss_score=5.0,
        observed_at=future_observed,
        source_confidence=0.7,
        tag_relevance=0.0,
        weights=DEFAULT_WEIGHTS,
        now=now,
    )

    # Score should be the same as if observed_at == now (age clamped to 0)
    score_now, _, _ = score_event(
        feed_type="rss",
        cvss_score=5.0,
        observed_at=now,
        source_confidence=0.7,
        tag_relevance=0.0,
        weights=DEFAULT_WEIGHTS,
        now=now,
    )

    assert math.isclose(score, score_now, abs_tol=1e-6), (
        f"Future observed_at should clamp to age=0: {score} vs {score_now}"
    )


def test_naive_observed_at_treated_as_utc() -> None:
    """Naive observed_at datetimes (no tzinfo) are treated as UTC."""
    now = FIXED_DT
    naive_observed = datetime(2026, 1, 15, 12, 0, 0)  # no tzinfo

    score_naive, _, _ = score_event(
        feed_type="nvd",
        cvss_score=5.0,
        observed_at=naive_observed,
        source_confidence=0.8,
        tag_relevance=0.5,
        weights=DEFAULT_WEIGHTS,
        now=now,
    )

    # Same event with explicit UTC
    aware_observed = naive_observed.replace(tzinfo=timezone.utc)
    score_aware, _, _ = score_event(
        feed_type="nvd",
        cvss_score=5.0,
        observed_at=aware_observed,
        source_confidence=0.8,
        tag_relevance=0.5,
        weights=DEFAULT_WEIGHTS,
        now=now,
    )

    assert math.isclose(score_naive, score_aware, abs_tol=1e-6)
