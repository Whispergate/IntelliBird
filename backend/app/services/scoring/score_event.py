"""Pure scoring function — no DB, no I/O.

Implements the composite 0–100 priority score formula locked in 15-CONTEXT.md:

    score = clamp(
        w_cvss * cvss_norm
        + w_recency * recency_factor
        + w_source * source_confidence
        + w_relevance * tag_relevance,
        0, 100
    )

Where:
    cvss_norm       = cvss_score / 10.0  (0–1 scale)
    recency_factor  = 2^(-age_days / half_life_days)  — in [0, 1]

No-CVSS events receive a synthetic CVSS derived from feed_type or brand_severity
so the formula stays uniform across all event types.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from .defaults import ScoringWeights

# Synthetic CVSS values assigned when no real CVSS is present (feed_type fallback).
SYNTHETIC_CVSS: dict[str, float] = {
    "rss": 5.0,
    "taxii": 6.0,
}

# Brand severity → synthetic CVSS mapping.
# brand_severity overrides feed_type when both would apply.
BRAND_SEVERITY_CVSS: dict[str, float] = {
    "low": 3.0,
    "medium": 6.0,
    "high": 8.0,
}


def score_event(
    *,
    feed_type: str,
    cvss_score: float | None,
    brand_severity: str | None = None,
    observed_at: datetime,
    source_confidence: float,
    tag_relevance: float,
    weights: ScoringWeights,
    now: datetime | None = None,
) -> tuple[float, datetime, int]:
    """Compute the composite 0–100 priority score for a single event.

    This function is pure — it performs no I/O and has no side effects.
    It is safe to call synchronously in the event INSERT pipeline.

    Args:
        feed_type:          Source feed type: ``'rss'``, ``'taxii'``, ``'nvd'``, etc.
        cvss_score:         Explicit CVSS base score [0–10], or ``None``.
        brand_severity:     Brand match severity (``'low'``, ``'medium'``, ``'high'``),
                            used when ``cvss_score`` is ``None``. Overrides feed_type
                            synthetic CVSS.
        observed_at:        Event observation timestamp (may be naive — treated as UTC).
        source_confidence:  Source reliability signal in [0.0, 1.0].
        tag_relevance:      Tag intersection signal: 0.0 (no match) or 1.0 (match).
        weights:            ``ScoringWeights`` dataclass (use ``ScoringWeights()`` for
                            bundled defaults).
        now:                Injectable clock for deterministic testing. Defaults to
                            ``datetime.now(timezone.utc)``.

    Returns:
        ``(score, scored_at, score_version)`` where:
            - ``score``         is in [0.0, 100.0]
            - ``scored_at``     is the ``now`` timestamp used for scoring
            - ``score_version`` is always ``1`` at ingest; rescores bump this via
                                ``event_score_overrides``
    """
    ts = now if now is not None else datetime.now(timezone.utc)

    # 1. CVSS normalisation (0–10 → 0–1)
    if cvss_score is not None:
        cvss_norm = cvss_score / 10.0
    elif brand_severity is not None:
        # Brand severity overrides feed_type synthetic when present.
        cvss_norm = BRAND_SEVERITY_CVSS.get(brand_severity, 5.0) / 10.0
    else:
        cvss_norm = SYNTHETIC_CVSS.get(feed_type, 5.0) / 10.0

    # 2. Recency decay — half-life formula.
    # Normalise observed_at to UTC if naive (clock skew from feed timestamps).
    if observed_at.tzinfo is None:
        observed_at_utc = observed_at.replace(tzinfo=timezone.utc)
    else:
        observed_at_utc = observed_at

    age_days = max(0.0, (ts - observed_at_utc).total_seconds() / 86400.0)
    recency_factor = math.pow(2.0, -age_days / weights.decay_half_life_days)

    # 3. Weighted sum — each weight is on the 0–100 scale, cvss_norm/recency_factor
    # are 0–1, source_confidence and tag_relevance are also 0–1.
    raw = (
        weights.cvss * cvss_norm
        + weights.recency * recency_factor
        + weights.source * source_confidence
        + weights.relevance * tag_relevance
    )

    # 4. Clamp to [0, 100]
    score = max(0.0, min(100.0, raw))

    # score_version=1 always at ingest; per-project rescores write to
    # event_score_overrides with version >= 2.
    return score, ts, 1
