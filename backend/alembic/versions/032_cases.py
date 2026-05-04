"""Case management foundation — cases, case_events, case_iocs tables + 2 ENUMs.

Revision ID: 032_cases
Revises: a3f8b2c
Create Date: 2026-05-04

Phase 31 / CASE-01, CASE-02.

Creates three tables that form the database foundation for case management:

  cases          Per-project investigation cases with status/severity lifecycle.
  case_events    M2M junction: case ↔ event (SOFT FK — events is a hypertable).
  case_iocs      M2M junction: case ↔ ioc (HARD FK — iocs is a regular table).

Design notes:
  * case_events.event_id is a SOFT FK (no REFERENCES clause) because events is a
    TimescaleDB hypertable; real FK constraints are not supported against hypertables.
    Matches precedent in campaign_events.event_id (migration 026).
  * case_iocs.ioc_id is a HARD FK (REFERENCES iocs(id) ON DELETE CASCADE) — iocs
    is a regular PostgreSQL table and FK constraints are safe.
  * ENUMs created via op.execute to match project pattern; column definitions use
    create_type=False so SQLAlchemy never attempts CREATE TYPE at migration time.
  * downgrade() drops tables in reverse dependency order then drops the ENUMs.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "032_cases"
down_revision = "a3f8b2c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create ENUMs (outside any table DDL so both tables can reference them)
    # ------------------------------------------------------------------
    op.execute(
        "CREATE TYPE case_status_enum AS ENUM "
        "('open', 'in_progress', 'on_hold', 'resolved', 'closed')"
    )
    op.execute(
        "CREATE TYPE case_severity_enum AS ENUM "
        "('low', 'medium', 'high', 'critical')"
    )

    # ------------------------------------------------------------------
    # 2. cases — per-project investigation case
    # ------------------------------------------------------------------
    op.create_table(
        "cases",
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
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="case_status_enum", create_type=False),
            nullable=False,
            server_default="open",
        ),
        sa.Column(
            "severity",
            postgresql.ENUM(name="case_severity_enum", create_type=False),
            nullable=True,
        ),
        sa.Column("assignee_user_sub", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("summary_md", sa.Text(), nullable=True),
        sa.Column(
            "opened_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("closed_at", sa.TIMESTAMP(timezone=True), nullable=True),
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
    op.create_index("ix_cases_project_id", "cases", ["project_id"])
    op.create_index("ix_cases_status", "cases", ["status"])

    # ------------------------------------------------------------------
    # 3. case_events — M2M case ↔ event (SOFT FK on event_id)
    # ------------------------------------------------------------------
    op.create_table(
        "case_events",
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        # event_id: soft FK — events is a TimescaleDB hypertable, no FK constraint
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "attached_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("attached_by", sa.Text(), nullable=True),
    )

    # ------------------------------------------------------------------
    # 4. case_iocs — M2M case ↔ ioc (HARD FK on ioc_id — iocs is not a hypertable)
    # ------------------------------------------------------------------
    op.create_table(
        "case_iocs",
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "ioc_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("iocs.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "attached_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("attached_by", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("case_iocs")
    op.drop_table("case_events")
    op.drop_index("ix_cases_status", table_name="cases")
    op.drop_index("ix_cases_project_id", table_name="cases")
    op.drop_table("cases")
    op.execute("DROP TYPE IF EXISTS case_severity_enum")
    op.execute("DROP TYPE IF EXISTS case_status_enum")
