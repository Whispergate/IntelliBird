"""Volume-drift detection for (MON-02).

Pure Python - no pandas dependency. EWMA over 168 hourly buckets (7 days)
using alpha = 2/(N+1) (standard EMA span formula). Z-score via stdlib statistics.

Alpha formula: alpha = 2 / (168 + 1) ≈ 0.012
  - span N = 168 (7 days × 24 hours of hourly buckets)
  - Standard EMA span-N formula: alpha = 2 / (N + 1)
  - Small alpha → slowly adapting baseline (correct - we want stability)

Locked thresholds from .planning/phases/16-continuous-monitoring/16-CONTEXT.md:
  - z > 3   → 'high' severity
  - 2 < z ≤ 3 → 'medium' severity
  - else    → no alert

Min-count guard: no alert when baseline_mean * 24 < 10 events/day.
Learning window: 7 days from source.created_at OR monitoring_config.last_changed_at
  - suppresses drift alerts during baseline ramp-up (M-5).
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Sequence

EWMA_ALPHA: float = 2 / (168 + 1)  # span = 168 hourly buckets (7 days)
MIN_BASELINE_POINTS: int = 24  # require >= 1 day of history
MIN_DAILY_EVENTS: int = 10  # min-count guard: < 10 events/day → no alert
LEARNING_WINDOW_DAYS: int = 7


def compute_ewma(values: Sequence[float], alpha: float = EWMA_ALPHA) -> list[float]:
    """Exponentially weighted moving average.

    Oldest-first input. Uses initialisation with first value (no warm-up bias).
    Formula per step: ewma[i] = alpha * values[i] + (1 - alpha) * ewma[i-1]
    """
    if not values:
        return []
    result = [float(values[0])]
    for v in values[1:]:
        result.append(alpha * float(v) + (1 - alpha) * result[-1])
    return result


def compute_z_score(hourly_counts: list[float], current_value: float) -> float | None:
    """Z-score of current_value vs the baseline distribution of hourly_counts.

    Returns None (no alert) when any guard trips:
    - Insufficient history: len(hourly_counts) < MIN_BASELINE_POINTS (< 24h)
    - Min-count guard: baseline_mean * 24 < MIN_DAILY_EVENTS (< 10/day)
    - Zero variance: stdev == 0 (constant baseline → no meaningful z-score)
    - Single-element baseline: statistics.stdev requires >= 2 data points

    Callers are expected to check is_in_learning_window() before calling this
    function - drift.py is pure math with no knowledge of source creation dates.
    """
    if len(hourly_counts) < MIN_BASELINE_POINTS:
        return None

    baseline_mean = statistics.mean(hourly_counts)
    if baseline_mean * 24 < MIN_DAILY_EVENTS:
        return None

    try:
        baseline_std = statistics.stdev(hourly_counts)
    except statistics.StatisticsError:
        # Raised when fewer than 2 data points (shouldn't happen given guard above)
        return None

    if baseline_std == 0:
        return None

    return (current_value - baseline_mean) / baseline_std


def classify_severity(
    z: float | None,
    z_high: float = 3.0,
    z_medium: float = 2.0,
) -> str | None:
    """Map a z-score to a severity label using locked CONTEXT.md thresholds.

    Locked thresholds:
      z > z_high  (default 3.0) → 'high'
      z > z_medium (default 2.0) → 'medium'
      else → None (no alert)

    Negative z (drift DOWN - volume drop) is intentionally not alerted here.
    Silence detection (MON-01) covers the case where a source goes quiet.
    """
    if z is None:
        return None
    if z > z_high:
        return "high"
    if z > z_medium:
        return "medium"
    return None


def is_in_learning_window(
    source_created_at: datetime,
    config_last_changed_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    """Return True when drift alerts should be suppressed due to ramp-up (M-5).

    Suppression triggers when either condition is met:
    - Source is younger than LEARNING_WINDOW_DAYS (7 days): baseline not yet stable
    - monitoring_config changed within LEARNING_WINDOW_DAYS: thresholds shifted,
      baseline no longer reflects the new operating point

    Args:
        source_created_at: Timezone-aware datetime of when the source was created.
        config_last_changed_at: Timezone-aware datetime of last monitoring_config
            change, or None if config has never been changed.
        now: Override for "now" - primarily for testing. Defaults to UTC now.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    threshold = timedelta(days=LEARNING_WINDOW_DAYS)

    if (now - source_created_at) < threshold:
        return True

    if config_last_changed_at is not None and (now - config_last_changed_at) < threshold:
        return True

    return False
