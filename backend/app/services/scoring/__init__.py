"""Scoring engine — pure functions and bundled defaults.

Public API (no I/O, no DB):
    - ``score_event``           — composite 0–100 scoring function
    - ``classify_tier``         — score → S/A/B/C/D tier classification
    - ``DEFAULT_SCORING_CONFIG``— bundled defaults constant (JSONB shape)
    - ``ScoringWeights``        — frozen dataclass for weight configuration
    - ``DEFAULT_TIER_CUTOFFS``  — default tier boundary dict
"""
from .defaults import DEFAULT_SCORING_CONFIG, DEFAULT_SOURCE_CONFIDENCE, DEFAULT_TIER_CUTOFFS, ScoringWeights
from .score_event import score_event
from .tiers import classify_tier

__all__ = [
    "DEFAULT_SCORING_CONFIG",
    "DEFAULT_SOURCE_CONFIDENCE",
    "DEFAULT_TIER_CUTOFFS",
    "ScoringWeights",
    "classify_tier",
    "score_event",
]
