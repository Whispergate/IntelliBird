"""Add certstream_enabled to projects, misp_configs table, extend brand_match_source and ioc_source_enum.

Revision ID: 033_certstream_misp
Revises: 032_cases
Create Date: 2026-05-05

schema:
  - brand_match_source ENUM: +certstream
  - ioc_source_enum: +misp
  - projects: +certstream_enabled BOOL DEFAULT FALSE
  - misp_configs: new table (one per project, encrypted API key)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "033_certstream_misp"
down_revision = "032_cases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. ENUM extensions — must run outside transaction (autocommit_block pattern)
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE brand_match_source ADD VALUE IF NOT EXISTS 'certstream'"
        )
        op.execute(
            "ALTER TYPE ioc_source_enum ADD VALUE IF NOT EXISTS 'misp'"
        )

    # 2. Add certstream_enabled column to projects (inside normal transaction)
    op.add_column(
        "projects",
        sa.Column(
            "certstream_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # 3. Create misp_configs table
    op.create_table(
        "misp_configs",
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
            unique=True,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("api_key_enc", sa.Text(), nullable=False),
        sa.Column(
            "pull_tags",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "push_types",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "ssl_verify",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("misp_configs")
    op.drop_column("projects", "certstream_enabled")
    # Note: ENUM value removal not supported in PostgreSQL — no-op for ENUM extensions
