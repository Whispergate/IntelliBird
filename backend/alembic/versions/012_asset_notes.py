"""asset_notes — operator-writable per-asset free-text note

Revision ID: 012
Revises: 011
Create Date: 2026-04-24

Phase 12.1 / Project Asset Surface from BBOT scan findings.

The project asset inventory surface is a query-time aggregation over
easm_findings. `asset_notes` is the sole stored write-state — a free-text
operator note keyed on the same (project_id, bbot_event_type, canonical_target)
tuple that makes easm_findings unique. Notes survive scan cleanup (no FK to
easm_findings); they are anchored to the project only.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_notes",
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
        sa.Column("bbot_event_type", sa.Text(), nullable=False),
        sa.Column("canonical_target", sa.Text(), nullable=False),
        sa.Column(
            "note",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "project_id",
            "bbot_event_type",
            "canonical_target",
            name="uq_asset_notes_project_type_target",
        ),
    )
    op.create_index(
        "ix_asset_notes_project_updated",
        "asset_notes",
        ["project_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_asset_notes_project_updated", table_name="asset_notes")
    op.drop_table("asset_notes")
