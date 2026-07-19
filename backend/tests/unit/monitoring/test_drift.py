"""MON-02 volume drift detection - plan 16-04.

Tests the EWMA z-score drift detection logic: severity thresholds, min-count
guard, learning window suppression, and the standard alpha formula.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


from app.services.monitoring.drift import (
    EWMA_ALPHA,
    MIN_BASELINE_POINTS,
    MIN_DAILY_EVENTS,
    LEARNING_WINDOW_DAYS,
    compute_ewma,
    compute_z_score,
    classify_severity,
    is_in_learning_window,
)


def test_ewma_alpha_formula() -> None:
    """Asserts alpha == 2 / (168 + 1) for span N=168 hourly buckets."""
    assert abs(EWMA_ALPHA - 2 / 169) < 1e-9


def test_high_severity() -> None:
    """z > 3 → 'high' severity alert.

    Baseline: 168 hours at 10 events/hour (mean=10, stdev≈0 → need variation).
    Use 168 values around 10 with variance so stdev > 0, current value at ~20.
    With constant baseline mean=10 and stdev=0 the function returns None;
    instead build a baseline with slight variation so stdev ≈ 1, then use
    current=20 which gives z ≈ 10 (>> 3) → 'high'.
    """
    import statistics

    baseline = [10.0 + (i % 3) * 0.5 for i in range(168)]  # slight variation
    mean = statistics.mean(baseline)
    std = statistics.stdev(baseline)
    # current value that puts us well above z=3
    current = mean + 4 * std

    z = compute_z_score(baseline, current)
    assert z is not None
    assert z > 3.0
    severity = classify_severity(z)
    assert severity == "high"


def test_medium_severity() -> None:
    """2 < z <= 3 → 'medium' severity alert."""
    import statistics

    baseline = [10.0 + (i % 5) * 1.0 for i in range(168)]  # stdev ~ 1.8
    mean = statistics.mean(baseline)
    std = statistics.stdev(baseline)
    # target z ≈ 2.5
    current = mean + 2.5 * std

    z = compute_z_score(baseline, current)
    assert z is not None
    assert 2.0 < z <= 3.0
    severity = classify_severity(z)
    assert severity == "medium"


def test_min_count_guard() -> None:
    """baseline_mean * 24 < 10 → compute_z_score returns None (min-count guard)."""
    # mean = 0.1 events/hour → 0.1 * 24 = 2.4 < 10
    baseline = [0.1] * 168
    result = compute_z_score(baseline, 5.0)
    assert result is None


def test_learning_window() -> None:
    """is_in_learning_window returns correct booleans based on age and config change."""
    now = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)

    # Source created 3 days ago → inside learning window
    created_3d = now - timedelta(days=3)
    assert is_in_learning_window(created_3d, None, now=now) is True

    # Source created 8 days ago, no config change → outside learning window
    created_8d = now - timedelta(days=8)
    assert is_in_learning_window(created_8d, None, now=now) is False

    # Source created 8 days ago, config changed 2 days ago → inside window
    config_changed_2d = now - timedelta(days=2)
    assert is_in_learning_window(created_8d, config_changed_2d, now=now) is True

    # Source created 8 days ago, config changed 8 days ago → outside window
    config_changed_8d = now - timedelta(days=8)
    assert is_in_learning_window(created_8d, config_changed_8d, now=now) is False


def test_compute_ewma_basic() -> None:
    """EWMA output: first value equals input; subsequent values follow alpha*v + (1-alpha)*prev."""
    values = [10.0, 20.0, 30.0]
    alpha = EWMA_ALPHA
    result = compute_ewma(values, alpha=alpha)

    assert len(result) == 3
    assert result[0] == 10.0
    expected_1 = alpha * 20.0 + (1 - alpha) * 10.0
    assert abs(result[1] - expected_1) < 1e-9
    expected_2 = alpha * 30.0 + (1 - alpha) * expected_1
    assert abs(result[2] - expected_2) < 1e-9


def test_compute_ewma_empty() -> None:
    """compute_ewma([]) → []."""
    assert compute_ewma([]) == []


def test_compute_z_score_insufficient_history() -> None:
    """Fewer than MIN_BASELINE_POINTS → returns None."""
    baseline = [10.0] * (MIN_BASELINE_POINTS - 1)
    result = compute_z_score(baseline, 20.0)
    assert result is None


def test_compute_z_score_zero_stdev() -> None:
    """Constant baseline (stdev == 0) → returns None."""
    baseline = [5.0] * 168
    result = compute_z_score(baseline, 10.0)
    assert result is None


def test_classify_severity_none_z() -> None:
    """classify_severity(None) → None."""
    assert classify_severity(None) is None


def test_classify_severity_negative_z() -> None:
    """Negative z (drift down) → None (not alerted)."""
    assert classify_severity(-5.0) is None


def test_classify_severity_low_z() -> None:
    """z <= 2 → None (below medium threshold)."""
    assert classify_severity(1.5) is None
    assert classify_severity(2.0) is None


def test_constants_values() -> None:
    """Verify locked constant values from CONTEXT.md."""
    assert MIN_BASELINE_POINTS == 24
    assert MIN_DAILY_EVENTS == 10
    assert LEARNING_WINDOW_DAYS == 7
