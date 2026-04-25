"""Pydantic v2 schemas for scoring rules API — Phase 15 / SCR-02, SCR-03.

Exports:
  ScoringWeightsPayload   — four-component weights block, validated sum=100
  TierCutoffsPayload      — S/A/B/C thresholds, validated strictly descending
  ScoringRulesPayload     — compound request body for PUT /scoring
  ScoringRulesRead        — response shape (project_id, version, rules, is_default)
  RescoreStatusResponse   — shape for GET /rescore/status
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScoringWeightsPayload(BaseModel):
    """Four-component scoring weights. Sum must equal 100.0 (±0.001 tolerance)."""

    cvss: float = Field(ge=0, le=100)
    recency: float = Field(ge=0, le=100)
    source: float = Field(ge=0, le=100)
    relevance: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def sum_eq_100(self) -> "ScoringWeightsPayload":
        total = self.cvss + self.recency + self.source + self.relevance
        if abs(total - 100.0) > 0.001:
            raise ValueError("weights must sum to 100")
        return self


class TierCutoffsPayload(BaseModel):
    """Tier threshold configuration. Cutoffs must be strictly descending: S > A > B > C > 0."""

    S: float
    A: float
    B: float
    C: float

    @model_validator(mode="after")
    def strictly_descending(self) -> "TierCutoffsPayload":
        if not (self.S > self.A > self.B > self.C > 0):
            raise ValueError("thresholds must be strictly descending: S > A > B > C > 0")
        return self


class ScoringRulesPayload(BaseModel):
    """Request body for PUT /api/projects/{id}/scoring.

    Pydantic validates weights sum + tier descending order automatically before
    the route body is available to the handler — malformed payloads return 422.
    """

    weights: ScoringWeightsPayload
    decay_half_life_days: float = Field(ge=1, le=365)
    tier_cutoffs: TierCutoffsPayload


class ScoringRulesRead(BaseModel):
    """Response shape for GET and PUT /api/projects/{id}/scoring.

    is_default=True when no project_scoring_rules row exists; the returned rules
    are the bundled DEFAULT_SCORING_CONFIG. is_default=False when an override row
    has been persisted by an admin for this project.
    """

    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    version: int
    rules: ScoringRulesPayload
    is_default: bool


class RescoreStatusResponse(BaseModel):
    """Response shape for GET /api/projects/{id}/rescore/status.

    in_progress_count: transient marker set by rescore_project actor. v1 returns
    0 when no Redis marker is present; polling-based "in progress" detection is
    deferred to M3 backlog. The UI poll lifecycle still works because it starts
    polling after PUT and stops when last_rescore_at advances.
    """

    last_rescore_at: datetime | None
    in_progress_count: int
    total_count: int
