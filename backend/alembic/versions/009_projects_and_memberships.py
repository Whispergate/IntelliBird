"""projects_and_memberships

Revision ID: 009_projects_and_memberships
Revises: 008_users_and_auth
Create Date: 2026-04-19

PRJ-01, PRJ-02, PRJ-05.

Creates project scoping foundation:
  - 3 ENUMs: engagement_type, scope_type, project_role (DO $$ EXCEPTION pattern per migration 003 precedent)
  - 4 new tables: projects, project_scope_rows, project_sources, project_memberships
  - project_id FK added to events, filter_presets, webhooks via three-step sentinel backfill (C-4 mitigation)
  - Composite index events_project_observed_idx for PROD-05 load-test gate
  - EASM pre-columns on projects (active_scans_authorised, scope_acknowledgement_text, active_auth_confirmed_at)
    - wires live

CONTEXT.md §Migration 007 shape locks the following:
  LEGACY_PROJECT_ID = '00000000-0000-0000-0000-000000000001'
  sentinel row: name='_legacy', engagement_type='intel_only',
                description='Pre-project-scoping legacy data (v1.5 events retained for audit).',
                archived=true, created_by='system', active_scans_authorised=false
  All three tables (events + filter_presets + webhooks) flip to NOT NULL post-backfill.
  No "global" row path.

Three-step-plus pattern - avoids the compressed-chunk SET NOT NULL risk AND
works with columnstore-enabled hypertables:
  1. INSERT sentinel row
  2a. ADD COLUMN project_id UUID NOT NULL DEFAULT sentinel::uuid
      (constant default -> TS 2.11+ backfills inline; column is born NOT NULL,
       never needs SET NOT NULL)
  2b. ADD CONSTRAINT ... FOREIGN KEY REFERENCES projects(id) ON DELETE RESTRICT
      (separated from 2a because TimescaleDB 2.26 rejects
       "ADD COLUMN ... REFERENCES" as a single statement on a hypertable whose
       columnstore is enabled - spike finding from plan 10-01 live dry-run)
  3. ALTER COLUMN project_id DROP DEFAULT
     (every new row onward must pass project_id explicitly - M-6)

No concurrent index creation here (TimescaleDB hypertables reject that form in a txn
per STATE.md lock) - standard CREATE INDEX propagates to all chunks.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009_projects_and_memberships"
down_revision: Union[str, None] = "008_users_and_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Sentinel project row id used for legacy data backfill. Must match the
#: LEGACY_PROJECT_ID constant exported from app.models.projects byte-for-byte.
LEGACY_PROJECT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # --- 1. ENUMs (idempotent creation, pattern from migration 003/006/008) ----
    op.execute(
        """
        DO $$ BEGIN
          CREATE TYPE engagement_type AS ENUM ('red_team', 'tiber', 'bbest', 'internal', 'intel_only');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
          CREATE TYPE scope_type AS ENUM ('keyword', 'service', 'domain', 'certificate', 'whois', 'as_number', 'ip_range');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
          CREATE TYPE project_role AS ENUM ('Lead', 'Contributor', 'Observer');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    # --- 2. projects table ---------------------------------------------------
    op.create_table(
        "projects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "engagement_type",
            postgresql.ENUM(
                "red_team", "tiber", "bbest", "internal", "intel_only",
                name="engagement_type", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "archived", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        # EASM pre-columns (wires live; ships read-only)
        sa.Column(
            "active_scans_authorised", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("scope_acknowledgement_text", sa.Text(), nullable=True),
        sa.Column(
            "active_auth_confirmed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("uq_projects_name", "projects", ["name"], unique=True)
    op.create_index(
        "ix_projects_archived", "projects", ["archived"],
        postgresql_where=sa.text("archived = false"),
    )

    # --- 3. project_scope_rows ----------------------------------------------
    op.create_table(
        "project_scope_rows",
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
        ),
        sa.Column(
            "scope_type",
            postgresql.ENUM(
                "keyword", "service", "domain", "certificate", "whois", "as_number", "ip_range",
                name="scope_type", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("contact", sa.Text(), nullable=True),
        sa.Column(
            "exclude", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "active_test_scope", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "intel_scope", sa.Boolean(), nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "active_test_scope OR intel_scope",
            name="project_scope_rows_at_least_one_flag",
        ),
        sa.UniqueConstraint(
            "project_id", "scope_type", "value", "exclude",
            name="uq_scope_rows_project_type_value_exclude",
        ),
    )
    op.create_index(
        "ix_scope_rows_project_type",
        "project_scope_rows",
        ["project_id", "scope_type"],
    )

    # --- 4. project_sources -------------------------------------------------
    op.create_table(
        "project_sources",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("project_id", "source_id", name="pk_project_sources"),
    )

    # --- 5. project_memberships --------------------------------------------
    op.create_table(
        "project_memberships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_sub", sa.Text(), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_role",
            postgresql.ENUM(
                "Lead", "Contributor", "Observer",
                name="project_role", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("added_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_sub", "project_id",
            name="uq_memberships_user_project",
        ),
    )
    op.create_index(
        "ix_memberships_user_sub", "project_memberships", ["user_sub"],
    )

    # --- 6. Sentinel project row (must exist BEFORE FK-add on events etc) --
    # UUID literal '00000000-0000-0000-0000-000000000001' intentionally inlined
    # here (and in the 3 ADD COLUMN DEFAULTs below) rather than f-string
    # interpolated - CONTEXT.md §Migration 007 shape mandates byte-for-byte
    # source readability, and the grep-check in plan 10-01 asserts exactly 4
    # literal occurrences.
    op.execute(
        """
        INSERT INTO projects
          (id, name, engagement_type, description, created_by, archived, active_scans_authorised)
        VALUES
          ('00000000-0000-0000-0000-000000000001'::uuid,
           '_legacy',
           'intel_only',
           'Pre-project-scoping legacy data (v1.5 events retained for audit).',
           'system',
           true,
           false)
        ON CONFLICT (id) DO NOTHING;
        """
    )

    # --- 7. Three-step backfill: events.project_id -------------------------
    # Spike finding (plan 10-01 live dry-run, 2026-04-19): TimescaleDB 2.26
    # rejects `ADD COLUMN ... REFERENCES` in one statement on a hypertable with
    # columnstore (compression) enabled - FeatureNotSupportedError: cannot add
    # column with constraints to a hypertable that has columnstore enabled.
    # Mitigation: split into two statements - first ADD COLUMN NOT NULL DEFAULT
    # (constant default backfills all chunks atomically per TS 2.11+ fast-path),
    # then ADD CONSTRAINT ... FOREIGN KEY. FK-only ALTER TABLE is permitted on
    # compressed hypertables.
    # Step A: ADD COLUMN with constant DEFAULT sentinel (no FK yet).
    op.execute(
        """
        ALTER TABLE events
        ADD COLUMN project_id UUID NOT NULL
        DEFAULT '00000000-0000-0000-0000-000000000001'::uuid;
        """
    )
    # Step B: Attach the FK constraint in a separate statement.
    op.execute(
        """
        ALTER TABLE events
        ADD CONSTRAINT events_project_id_fkey
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT;
        """
    )
    # Step C: DROP DEFAULT. Every new event onward must pass
    # project_id explicitly (M-6).
    op.execute("ALTER TABLE events ALTER COLUMN project_id DROP DEFAULT;")

    # --- 8. Three-step backfill: filter_presets.project_id ----------------
    # filter_presets is a regular PG table (not a hypertable) so the single-
    # statement form would work, but we keep the split form for uniformity.
    op.execute(
        """
        ALTER TABLE filter_presets
        ADD COLUMN project_id UUID NOT NULL
        DEFAULT '00000000-0000-0000-0000-000000000001'::uuid;
        """
    )
    op.execute(
        """
        ALTER TABLE filter_presets
        ADD CONSTRAINT filter_presets_project_id_fkey
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT;
        """
    )
    op.execute("ALTER TABLE filter_presets ALTER COLUMN project_id DROP DEFAULT;")

    # --- 9. Three-step backfill: webhooks.project_id ---------------------
    op.execute(
        """
        ALTER TABLE webhooks
        ADD COLUMN project_id UUID NOT NULL
        DEFAULT '00000000-0000-0000-0000-000000000001'::uuid;
        """
    )
    op.execute(
        """
        ALTER TABLE webhooks
        ADD CONSTRAINT webhooks_project_id_fkey
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT;
        """
    )
    op.execute("ALTER TABLE webhooks ALTER COLUMN project_id DROP DEFAULT;")

    # --- 10. Composite index (PROD-05 load-test gate) + single-column indexes
    op.execute(
        "CREATE INDEX events_project_observed_idx "
        "ON events (project_id, observed_at DESC);"
    )
    op.create_index(
        "ix_filter_presets_project_id", "filter_presets", ["project_id"],
    )
    op.create_index(
        "ix_webhooks_project_id", "webhooks", ["project_id"],
    )


def downgrade() -> None:
    # Reverse in strict opposite order
    op.drop_index("ix_webhooks_project_id", table_name="webhooks")
    op.drop_index("ix_filter_presets_project_id", table_name="filter_presets")
    op.execute("DROP INDEX IF EXISTS events_project_observed_idx;")

    op.execute("ALTER TABLE webhooks DROP COLUMN project_id;")
    op.execute("ALTER TABLE filter_presets DROP COLUMN project_id;")
    op.execute("ALTER TABLE events DROP COLUMN project_id;")

    op.drop_index("ix_memberships_user_sub", table_name="project_memberships")
    op.drop_table("project_memberships")
    op.drop_table("project_sources")
    op.drop_index("ix_scope_rows_project_type", table_name="project_scope_rows")
    op.drop_table("project_scope_rows")
    op.drop_index("ix_projects_archived", table_name="projects")
    op.drop_index("uq_projects_name", table_name="projects")
    op.drop_table("projects")

    op.execute("DROP TYPE IF EXISTS project_role;")
    op.execute("DROP TYPE IF EXISTS scope_type;")
    op.execute("DROP TYPE IF EXISTS engagement_type;")
