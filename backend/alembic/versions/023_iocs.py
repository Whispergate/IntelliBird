"""IOC foundation — iocs + ioc_event_links + 3 ENUM types.

Revision ID: 019_iocs
Revises: 018_ai_auto_summary_toggle
Create Date: 2026-05-03

IOC-01, IOC-08.

Schema-only migration. Backfill of `iocs` from existing events is a separate
concern — handled by the admin endpoint POST /api/admin/iocs/backfill which
delegates to the same Dramatiq actor used by bulk-import (Plan 22-04).

Key decisions (see .planning/phases/22-ioc-foundation/22-CONTEXT.md):
  * project_id NULLABLE — NULL = global "known bad" row visible to all projects.
  * UNIQUE (project_id, type, normalized_value) NULLS NOT DISTINCT — PG15+ — so
    two (NULL, 'ip', '1.2.3.4') rows collide as expected.
  * 13-value ioc_type_enum locked at this migration — adding a new type
    requires a new alembic revision.
  * ioc_event_links.event_id is a SOFT FK (no constraint) — events is a
    TimescaleDB hypertable and hypertables cannot cleanly be FK targets;
    same precedent as brand_matches.event_id.

NOTE: revision id uses the slug-style established by recent migrations
(017_events_dedup_per_project, 018_ai_auto_summary_toggle); filename retains
the sequential 023_ prefix for filesystem ordering.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "019_iocs"
down_revision: Union[str, None] = "018_ai_auto_summary_toggle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


IOC_TYPES = (
    "ip", "ipv6", "domain", "url", "sha256", "sha1", "md5",
    "email", "btc", "eth", "mutex", "registry_key", "filename",
)
IOC_STATUSES = ("active", "expired", "whitelisted")
IOC_SOURCES = ("manual", "csv", "json", "stix", "event", "backfill")


def upgrade() -> None:
    # --- ENUM types (idempotent re-creation pattern from 006_webhooks) -------
    op.execute(
        f"""
        DO $$ BEGIN
            CREATE TYPE ioc_type_enum AS ENUM ({",".join(f"'{t}'" for t in IOC_TYPES)});
        EXCEPTION WHEN duplicate_object THEN null; END $$;
        """
    )
    op.execute(
        f"""
        DO $$ BEGIN
            CREATE TYPE ioc_status_enum AS ENUM ({",".join(f"'{s}'" for s in IOC_STATUSES)});
        EXCEPTION WHEN duplicate_object THEN null; END $$;
        """
    )
    op.execute(
        f"""
        DO $$ BEGIN
            CREATE TYPE ioc_source_enum AS ENUM ({",".join(f"'{s}'" for s in IOC_SOURCES)});
        EXCEPTION WHEN duplicate_object THEN null; END $$;
        """
    )

    # --- iocs --------------------------------------------------------------
    op.create_table(
        "iocs",
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
            nullable=True,
        ),
        sa.Column(
            "type",
            postgresql.ENUM(*IOC_TYPES, name="ioc_type_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(*IOC_STATUSES, name="ioc_status_enum", create_type=False),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "confidence",
            sa.Numeric(3, 2),
            nullable=False,
            server_default=sa.text("0.7"),
        ),
        sa.Column("ttl_days", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            postgresql.ENUM(*IOC_SOURCES, name="ioc_source_enum", create_type=False),
            nullable=False,
            server_default="manual",
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
        sa.Column("created_by", sa.Text(), nullable=True),
    )

    # NULLS NOT DISTINCT (PG15+) — two (NULL,'ip','1.2.3.4') rows collide.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_iocs_project_type_value
        ON iocs (project_id, type, normalized_value) NULLS NOT DISTINCT
        """
    )
    op.create_index("ix_iocs_project_id", "iocs", ["project_id"])
    op.create_index("ix_iocs_type", "iocs", ["type"])
    op.create_index("ix_iocs_status", "iocs", ["status"])
    op.create_index("ix_iocs_last_seen", "iocs", ["last_seen"])
    op.create_index("ix_iocs_normalized_value", "iocs", ["normalized_value"])

    # --- ioc_event_links ---------------------------------------------------
    op.create_table(
        "ioc_event_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "ioc_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("iocs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SOFT FK to events hypertable — no constraint, mirrors brand_matches.event_id.
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "observed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("source_field", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "ioc_id", "event_id", name="uq_ioc_event_links_ioc_event"
        ),
    )
    op.create_index("ix_ioc_event_links_ioc_id", "ioc_event_links", ["ioc_id"])
    op.create_index("ix_ioc_event_links_event_id", "ioc_event_links", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_ioc_event_links_event_id", table_name="ioc_event_links")
    op.drop_index("ix_ioc_event_links_ioc_id", table_name="ioc_event_links")
    op.drop_table("ioc_event_links")

    op.drop_index("ix_iocs_normalized_value", table_name="iocs")
    op.drop_index("ix_iocs_last_seen", table_name="iocs")
    op.drop_index("ix_iocs_status", table_name="iocs")
    op.drop_index("ix_iocs_type", table_name="iocs")
    op.drop_index("ix_iocs_project_id", table_name="iocs")
    op.execute("DROP INDEX IF EXISTS uq_iocs_project_type_value")
    op.drop_table("iocs")

    op.execute("DROP TYPE IF EXISTS ioc_source_enum")
    op.execute("DROP TYPE IF EXISTS ioc_status_enum")
    op.execute("DROP TYPE IF EXISTS ioc_type_enum")
