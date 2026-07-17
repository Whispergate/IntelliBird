"""Scoring engine ORM models.

SCR-01, SCR-03.

EventScoreOverride — per-project admin score overrides keyed on (event_id, score_version).
  event_id is a soft UUID (no FK to events.id) because events is a TimescaleDB hypertable and
  cannot be a FK target. Same pattern as brand_matches.event_id (migration 011).

ProjectScoringRules — per-project weight / decay / tier cutoff overrides.
  One row per project (UNIQUE on project_id). The rules JSONB column stores:
    {
      "weights": {"cvss": 50, "recency": 20, "source": 15, "relevance": 15},
      "decay_half_life_days": 14,
      "tier_cutoffs": {"S": 90, "A": 75, "B": 55, "C": 30}
    }
  If no row exists for a project, the scoring service falls back to DEFAULT_SCORING_CONFIG
  from app.services.scoring.defaults.

Schema created by migration 013_scoring.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Integer, Numeric, PrimaryKeyConstraint, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EventScoreOverride(Base):
    """Per-project scoring override for a specific event version.

    PK is (event_id, score_version) — composite primary key allows multiple
    version rows per event while read path uses ORDER BY score_version DESC LIMIT 1.

    project_id FK to projects.id (CASCADE DELETE) enables PROD-01 isolation:
    a query scoped to Project A cannot surface Project B overrides.
    """

    __tablename__ = "event_score_overrides"

    # Soft UUID — no FK to events.id; events is a hypertable (cannot be FK target).
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    score_version: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    scored_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        PrimaryKeyConstraint("event_id", "score_version"),
    )


class ProjectScoringRules(Base):
    """Per-project scoring weight / decay / tier cutoff configuration.

    One row per project enforced by UNIQUE constraint on project_id.
    Absence of a row means the project inherits DEFAULT_SCORING_CONFIG from
    app.services.scoring.defaults (SCR-02).

    version is monotonically incremented each time an admin saves new rules;
    the rescore_project Dramatiq actor uses this version as score_version when
    writing to event_score_overrides.
    """

    __tablename__ = "project_scoring_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    rules: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
