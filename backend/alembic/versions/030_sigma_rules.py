"""030 — sigma_rules table for Phase 29 Sigma Rule Engine.

Revision ID: 030_sigma_rules
Revises: 029_passive_dns_whois_age
Create Date: 2026-05-04

sigma_rules: stored Sigma detection rules (global or per-project).

Design notes:
  * project_id is nullable — NULL = global rule visible to all projects
    (admin-curated). Per-project rules are scoped by project_id filter.
  * compiled_cache is JSONB (not LargeBinary) — Sigma rules compile to a
    Python dict structure (field mappings, detection conditions) rather than
    a binary blob. JSONB enables introspection and partial updates.
  * level (TEXT, nullable) mirrors Sigma's native severity field:
    informational | low | medium | high | critical
  * tags (ARRAY of TEXT, nullable) stores raw Sigma rule tags such as
    attack.t1566 — used for MITRE technique tagging of matched events.
  * Two partial indexes: project_id (FK lookups) and enabled=TRUE
    (warm path for scanner job — only scans enabled rules).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "030_sigma_rules"
down_revision: Union[str, None] = "029_passive_dns_whois_age"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sigma_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("compiled_cache", JSONB, nullable=True),
        sa.Column("level", sa.Text, nullable=True),
        sa.Column("tags", sa.ARRAY(sa.Text), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
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
    op.create_index("ix_sigma_rules_project_id", "sigma_rules", ["project_id"])
    op.create_index(
        "ix_sigma_rules_enabled",
        "sigma_rules",
        ["enabled"],
        postgresql_where=sa.text("enabled = TRUE"),
    )


def downgrade() -> None:
    op.drop_index("ix_sigma_rules_enabled", table_name="sigma_rules")
    op.drop_index("ix_sigma_rules_project_id", table_name="sigma_rules")
    op.drop_table("sigma_rules")
