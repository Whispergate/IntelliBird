"""Brand Protection — brand_terms + brand_matches + projects.gdpr_person_match_retention_days

Revision ID: 011
Revises: 010_easm
Create Date: 2026-04-22

BRP-01..BRP-05.

Creates Brand Protection schema foundation:
  - 5 ENUMs: brand_term_type, brand_term_mode, brand_match_source,
             brand_match_severity, brand_match_lifecycle_status
             (DO $$ EXCEPTION pattern — matches migration 010 precedent)
  - 2 new tables: brand_terms, brand_matches
  - projects gains gdpr_person_match_retention_days INT NOT NULL DEFAULT 90

Design notes:
  * brand_matches.event_id is a soft UUID column with NO FK to events.id —
    events is a TimescaleDB hypertable (see 001_initial_schema.py:171 precedent);
    hypertables cannot be FK targets (requires unique index including partition
    column). App enforces referential integrity. Same precedent as
    attack_technique_tags.event_id and cve_details.event_id.
  * Case-insensitive UNIQUE on brand_terms is expressed via functional index on
    lower(value) — plain UNIQUE constraint cannot express lower() expression.
  * ix_brand_matches_dismiss_until is a partial index (WHERE lifecycle_status='dismissed')
    to keep the scheduler "find expiring dismissals" probe cheap.
  * brand_matches is NOT a hypertable — project-scoped, not pure time-series
    (H-4 pattern from easm_findings).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "011"
down_revision: Union[str, None] = "010_easm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. ENUMs (idempotent creation — DO $$ EXCEPTION pattern) ------------
    op.execute("""
    DO $$ BEGIN
        CREATE TYPE brand_term_type AS ENUM ('keyword','domain','product','person');
    EXCEPTION WHEN duplicate_object THEN null; END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        CREATE TYPE brand_term_mode AS ENUM ('active','watch_only');
    EXCEPTION WHEN duplicate_object THEN null; END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        CREATE TYPE brand_match_source AS ENUM ('fts','ct_log','dnstwist');
    EXCEPTION WHEN duplicate_object THEN null; END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        CREATE TYPE brand_match_severity AS ENUM ('low','medium','high');
    EXCEPTION WHEN duplicate_object THEN null; END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        CREATE TYPE brand_match_lifecycle_status AS ENUM ('new','confirmed','dismissed','watchlist');
    EXCEPTION WHEN duplicate_object THEN null; END $$;
    """)

    # --- 2. brand_terms ------------------------------------------------------
    op.create_table(
        "brand_terms",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "term_type",
            postgresql.ENUM(name="brand_term_type", create_type=False),
            nullable=False,
        ),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "mode",
            postgresql.ENUM(name="brand_term_mode", create_type=False),
            nullable=False,
            server_default="active",
        ),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("high_noise_risk", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Case-insensitive UNIQUE via functional index on lower(value)
    op.execute("""
        CREATE UNIQUE INDEX ux_brand_terms_project_type_value
        ON brand_terms (project_id, term_type, lower(value))
    """)
    op.create_index(
        "ix_brand_terms_project_archived",
        "brand_terms",
        ["project_id", "archived"],
    )

    # --- 3. brand_matches ----------------------------------------------------
    op.create_table(
        "brand_matches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "brand_term_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("brand_terms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("matched_value", sa.Text(), nullable=False),
        sa.Column(
            "match_source",
            postgresql.ENUM(name="brand_match_source", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "severity",
            postgresql.ENUM(name="brand_match_severity", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "first_seen",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("match_metadata", postgresql.JSONB(), nullable=True),
        # NOTE: no FK to events.id — events is a TimescaleDB hypertable and
        # cannot be a FK target. Soft reference only; app enforces integrity.
        # Same precedent as attack_technique_tags.event_id (migration 001).
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "lifecycle_status",
            postgresql.ENUM(name="brand_match_lifecycle_status", create_type=False),
            nullable=False,
            server_default="new",
        ),
        sa.Column("dismiss_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("webhook_fired_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "project_id", "brand_term_id", "matched_value", "match_source",
            name="ux_brand_matches_dedup",
        ),
    )
    op.create_index(
        "ix_brand_matches_project_last_seen",
        "brand_matches",
        ["project_id", sa.text("last_seen DESC")],
    )
    # Partial index — only rows awaiting resurface
    op.execute("""
        CREATE INDEX ix_brand_matches_dismiss_until
        ON brand_matches (dismiss_until)
        WHERE lifecycle_status = 'dismissed'
    """)

    # --- 4. projects.gdpr_person_match_retention_days ------------------------
    op.add_column(
        "projects",
        sa.Column(
            "gdpr_person_match_retention_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("90"),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "gdpr_person_match_retention_days")
    op.execute("DROP INDEX IF EXISTS ix_brand_matches_dismiss_until")
    op.drop_index("ix_brand_matches_project_last_seen", table_name="brand_matches")
    op.drop_table("brand_matches")
    op.drop_index("ix_brand_terms_project_archived", table_name="brand_terms")
    op.execute("DROP INDEX IF EXISTS ux_brand_terms_project_type_value")
    op.drop_table("brand_terms")
    op.execute("DROP TYPE IF EXISTS brand_match_lifecycle_status;")
    op.execute("DROP TYPE IF EXISTS brand_match_severity;")
    op.execute("DROP TYPE IF EXISTS brand_match_source;")
    op.execute("DROP TYPE IF EXISTS brand_term_mode;")
    op.execute("DROP TYPE IF EXISTS brand_term_type;")
