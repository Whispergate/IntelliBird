"""easm: scans + findings + credentials + gate-audit column + events provenance FK

Revision ID: 010_easm
Revises: 009_projects_and_memberships
Create Date: 2026-04-21

EASM-01, EASM-02, EASM-04, EASM-06, EASM-10.

Creates EASM data foundation:
  - 5 ENUMs: easm_scan_status, easm_scan_mode, easm_severity, easm_lifecycle,
             easm_credential_provider (DO $$ EXCEPTION pattern per migration 003/009 precedent)
  - 3 new tables: easm_scans, easm_findings, project_easm_credentials
  - projects gains active_auth_confirmed_by TEXT NULL (gate-audit column)
  - events gains easm_scan_id UUID NULL FK → easm_scans(id) ON DELETE SET NULL (L-4)

L-4 closure: promoted events survive scan cleanup via ON DELETE SET NULL.
H-4 pitfall: easm_findings is NOT a TimescaleDB hypertable — no time-series partitioning.
M-4 dedup: UNIQUE(project_id, bbot_event_type, canonical_target) enforces cross-scan dedup.
No CREATE INDEX CONCURRENTLY — TimescaleDB hypertables reject that form.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "010_easm"
down_revision: Union[str, None] = "009_projects_and_memberships"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. ENUMs (idempotent creation, pattern from migration 003/008/009) ---
    op.execute("""
    DO $$ BEGIN
        CREATE TYPE easm_scan_status AS ENUM ('queued','running','finished','failed','cancelled','orphaned');
    EXCEPTION WHEN duplicate_object THEN null; END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        CREATE TYPE easm_scan_mode AS ENUM ('passive','active');
    EXCEPTION WHEN duplicate_object THEN null; END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        CREATE TYPE easm_severity AS ENUM ('low','medium','high','critical');
    EXCEPTION WHEN duplicate_object THEN null; END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        CREATE TYPE easm_lifecycle AS ENUM ('new','confirmed','dismissed','watchlist');
    EXCEPTION WHEN duplicate_object THEN null; END $$;
    """)
    op.execute("""
    DO $$ BEGIN
        CREATE TYPE easm_credential_provider AS ENUM ('shodan','github','bevigil','chaos','securitytrails');
    EXCEPTION WHEN duplicate_object THEN null; END $$;
    """)

    # --- 2. easm_scans --------------------------------------------------------
    op.create_table(
        "easm_scans",
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
            "status",
            postgresql.ENUM(name="easm_scan_status", create_type=False),
            nullable=False,
            server_default="queued",
        ),
        sa.Column(
            "scan_mode",
            postgresql.ENUM(name="easm_scan_mode", create_type=False),
            nullable=False,
        ),
        sa.Column("modules", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("container_id", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "stdout_bytes",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("launched_by", sa.Text(), nullable=False),
    )
    # Standard index — no CREATE INDEX CONCURRENTLY (TimescaleDB incompat)
    op.create_index(
        "ix_easm_scans_project_started",
        "easm_scans",
        ["project_id", sa.text("started_at DESC")],
    )

    # --- 3. easm_findings (NOT a hypertable — H-4) ----------------------------
    op.create_table(
        "easm_findings",
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
            "scan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("easm_scans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("bbot_event_type", sa.Text(), nullable=False),
        sa.Column("canonical_target", sa.Text(), nullable=False),
        sa.Column(
            "severity",
            postgresql.ENUM(name="easm_severity", create_type=False),
            nullable=True,
        ),
        sa.Column("module", sa.Text(), nullable=False),
        sa.Column("raw_bbot", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column(
            "first_seen",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "last_seen",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "lifecycle_status",
            postgresql.ENUM(name="easm_lifecycle", create_type=False),
            nullable=False,
            server_default="new",
        ),
        sa.Column("dismiss_until", sa.TIMESTAMP(timezone=True), nullable=True),
        # M-4 dedup key — cross-scan deduplication: same target in any scan = one row
        sa.UniqueConstraint(
            "project_id", "bbot_event_type", "canonical_target",
            name="uq_easm_findings_dedup",
        ),
    )
    op.create_index(
        "ix_easm_findings_project_last_seen",
        "easm_findings",
        ["project_id", sa.text("last_seen DESC")],
    )
    op.create_index("ix_easm_findings_scan_id", "easm_findings", ["scan_id"])

    # --- 4. project_easm_credentials ------------------------------------------
    op.create_table(
        "project_easm_credentials",
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
            "provider",
            postgresql.ENUM(name="easm_credential_provider", create_type=False),
            nullable=False,
        ),
        sa.Column("credentials_enc", sa.LargeBinary(), nullable=False),
        sa.Column(
            "credentials_key_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "project_id", "provider",
            name="uq_project_easm_credentials_provider",
        ),
    )

    # --- 5. projects.active_auth_confirmed_by (gate-audit column) -------------
    op.add_column(
        "projects",
        sa.Column("active_auth_confirmed_by", sa.Text(), nullable=True),
    )

    # --- 6. events.easm_scan_id — L-4: ON DELETE SET NULL so promoted events  --
    #        survive scan cleanup
    op.add_column(
        "events",
        sa.Column("easm_scan_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_events_easm_scan_id",
        "events",
        "easm_scans",
        ["easm_scan_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Reverse in strict opposite order
    op.drop_constraint("fk_events_easm_scan_id", "events", type_="foreignkey")
    op.drop_column("events", "easm_scan_id")
    op.drop_column("projects", "active_auth_confirmed_by")
    op.drop_table("project_easm_credentials")
    op.drop_index("ix_easm_findings_scan_id", table_name="easm_findings")
    op.drop_index("ix_easm_findings_project_last_seen", table_name="easm_findings")
    op.drop_table("easm_findings")
    op.drop_index("ix_easm_scans_project_started", table_name="easm_scans")
    op.drop_table("easm_scans")
    op.execute("DROP TYPE IF EXISTS easm_credential_provider;")
    op.execute("DROP TYPE IF EXISTS easm_lifecycle;")
    op.execute("DROP TYPE IF EXISTS easm_severity;")
    op.execute("DROP TYPE IF EXISTS easm_scan_mode;")
    op.execute("DROP TYPE IF EXISTS easm_scan_status;")
