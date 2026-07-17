"""Per-project brand stoplist terms table — BRAND-01.

Revision ID: 016_brand_stoplist
Revises: 015_tiber
Create Date: 2026-04-29

Creates brand_stoplist_terms:
  - id UUID PK default gen_random_uuid()
  - project_id UUID NOT NULL FK projects(id) ON DELETE CASCADE
  - term TEXT NOT NULL
  - created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  - created_by_user_id UUID FK users(id) ON DELETE SET NULL nullable

Unique index: brand_stoplist_terms_term_lower_unique ON (project_id, lower(term))
  — operator stores term as-typed; case-insensitive dedup enforced via lower().

Regular index: ix_brand_stoplist_project ON (project_id) for scan_project load.

Design notes:
  * UNIQUE is expressed via functional index on lower(term) — plain UNIQUE
    cannot express lower() expression (same pattern as migration 011 brand_terms).
  * project_id ON DELETE CASCADE — row automatically removed when project deleted.
  * created_by_user_id ON DELETE SET NULL — preserves history after user deletion.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "016_brand_stoplist"
down_revision: Union[str, None] = "015_tiber"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brand_stoplist_terms",
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
        sa.Column("term", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Case-insensitive UNIQUE via functional index on lower(term) scoped to project
    op.execute(
        """
        CREATE UNIQUE INDEX brand_stoplist_terms_term_lower_unique
        ON brand_stoplist_terms (project_id, lower(term))
        """
    )

    # Regular index for fast lookup per project during scan_project()
    op.create_index(
        "ix_brand_stoplist_project",
        "brand_stoplist_terms",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_brand_stoplist_project", table_name="brand_stoplist_terms")
    op.execute("DROP INDEX IF EXISTS brand_stoplist_terms_term_lower_unique")
    op.drop_table("brand_stoplist_terms")
