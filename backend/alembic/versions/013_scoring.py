"""scoring - score columns on events + event_score_overrides + project_scoring_rules + sources.confidence

Revision ID: 013_scoring
Revises: 012_asset_notes
Create Date: 2026-04-25

SCR-01, SCR-03.

Schema foundation for the scoring engine:
  - events hypertable gains score numeric(5,2), scored_at timestamptz, score_version int (all nullable)
    SCR-01: composite 0-100 score stored at ingest; NULL for pre-migration rows (COALESCE handles)
  - ix_events_project_score index on events (project_id, score DESC) for score-sort query path
  - event_score_overrides side table: per-project admin overrides, PK (event_id, score_version)
    event_id is a soft UUID (no FK to events.id) - events is a hypertable and cannot be FK target.
    Same pattern as attack_technique_tags.event_id (migration 001), cve_details.event_id (001),
    brand_matches.event_id (migration 011).
  - project_scoring_rules table: per-project weight/decay/tier overrides, UNIQUE project_id FK
    SCR-03: required for PROD-01 regression (Project A rules cannot influence Project B scores)
  - sources.confidence numeric(3,2) added, backfilled per feed_type:
    taxii=1.0, nvd=1.0, rss=0.7

ADD COLUMN safety note (from migration 009 spike finding):
  TimescaleDB 2.26 rejects "ADD COLUMN ... REFERENCES" as a single statement on a hypertable
  whose columnstore is enabled (FeatureNotSupportedError: cannot add column with constraints to
  a hypertable that has columnstore enabled). For the three score columns we only add nullable
  columns with no FK or NOT NULL constraint - each as a separate op.execute() call is safe.
  No combined "ADD COLUMN + constraint" anywhere in this migration.

No CONCURRENT index creation (TimescaleDB hypertables reject that form inside a transaction per
migration 009 note). Standard CREATE INDEX propagates to all chunks automatically.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "013_scoring"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. events hypertable: three separate ADD COLUMN statements ------------------
    # Each ADD COLUMN is its own statement - required because events is a TimescaleDB
    # hypertable with columnstore enabled (migration 009 precedent: "ADD COLUMN with
    # constraint not supported on compressed hypertable - split each ADD COLUMN into a
    # separate statement"). These columns are nullable with no FK, so single statements
    # are safe, but we keep them separate for clarity and consistency.
    op.execute("ALTER TABLE events ADD COLUMN score numeric(5,2) NULL;")
    op.execute("ALTER TABLE events ADD COLUMN scored_at timestamptz NULL;")
    op.execute("ALTER TABLE events ADD COLUMN score_version int NULL;")

    # --- 2. Score sort index on events -----------------------------------------------
    # NOT CONCURRENTLY - TimescaleDB hypertables reject concurrent index in a transaction.
    # Standard CREATE INDEX propagates to all chunks automatically.
    op.execute("CREATE INDEX ix_events_project_score ON events (project_id, score DESC);")

    # --- 3. event_score_overrides side table -----------------------------------------
    # event_id is a soft UUID - no FK to events.id because events is a hypertable and
    # cannot be a FK target (same pattern as brand_matches.event_id in migration 011).
    op.create_table(
        "event_score_overrides",
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score_version", sa.Integer(), nullable=False),
        sa.Column("score", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "scored_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("event_id", "score_version"),
    )

    # --- 4. Indexes on event_score_overrides -----------------------------------------
    op.execute(
        "CREATE INDEX ix_eso_event_version "
        "ON event_score_overrides (event_id, score_version DESC);"
    )
    op.execute(
        "CREATE INDEX ix_eso_project "
        "ON event_score_overrides (project_id);"
    )

    # --- 5. project_scoring_rules table ----------------------------------------------
    # UNIQUE on project_id - one rule-set per project. JSONB rules column stores
    # weights, decay_half_life_days, tier_cutoffs (see RESEARCH.md §Pattern 1).
    op.create_table(
        "project_scoring_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "rules",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- 6. sources.confidence column ------------------------------------------------
    # nullable - not all existing sources have a feed_type-derived confidence yet.
    # Backfill applied immediately below via UPDATE (sources is a normal table, not a
    # hypertable; safe to UPDATE in a migration transaction).
    op.execute("ALTER TABLE sources ADD COLUMN confidence numeric(3,2) NULL;")

    # --- 7. Backfill confidence per feed_type ----------------------------------------
    # TAXII and NVD are authoritative/curated feeds → 1.0
    # RSS general feeds are lower fidelity → 0.7
    # Any feed_type not matched (custom) is left NULL - pipeline sets on first ingest.
    op.execute("UPDATE sources SET confidence = 1.0 WHERE feed_type = 'taxii';")
    op.execute("UPDATE sources SET confidence = 1.0 WHERE feed_type = 'nvd';")
    op.execute("UPDATE sources SET confidence = 0.7 WHERE feed_type = 'rss';")


def downgrade() -> None:
    # Reverse order of upgrade

    # --- 1. Drop project_scoring_rules -----------------------------------------------
    op.drop_table("project_scoring_rules")

    # --- 2. Drop event_score_overrides (indexes first) -------------------------------
    op.execute("DROP INDEX IF EXISTS ix_eso_project;")
    op.execute("DROP INDEX IF EXISTS ix_eso_event_version;")
    op.drop_table("event_score_overrides")

    # --- 3. Drop events score sort index ---------------------------------------------
    op.execute("DROP INDEX IF EXISTS ix_events_project_score;")

    # --- 4. Drop events score columns (reverse add order) ----------------------------
    op.execute("ALTER TABLE events DROP COLUMN score_version;")
    op.execute("ALTER TABLE events DROP COLUMN scored_at;")
    op.execute("ALTER TABLE events DROP COLUMN score;")

    # --- 5. Drop sources.confidence --------------------------------------------------
    op.execute("ALTER TABLE sources DROP COLUMN confidence;")
