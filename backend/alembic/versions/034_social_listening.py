"""Add social_listening feed type, source_config column, cib_clusters table.

Phase 33 — DISINFO-01, DISINFO-02.
Also extends ai_suggestion_type_enum with 'narrative_op' (DISINFO-03).

Revision ID: 034_social_listening
Revises: 033_certstream_misp
Create Date: 2026-05-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "034_social_listening"
down_revision = "033_certstream_misp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ENUM extensions MUST be in autocommit_block (Postgres DDL constraint)
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE feed_type_enum ADD VALUE IF NOT EXISTS 'social_listening'"
        )
        op.execute(
            "ALTER TYPE ai_suggestion_type_enum ADD VALUE IF NOT EXISTS 'narrative_op'"
        )

    # source_config JSONB column on sources table
    op.add_column(
        "sources",
        sa.Column(
            "source_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment=(
                "Social listening source config: platform, instance_url, board, "
                "subreddit, topic_keywords, poll_interval_seconds"
            ),
        ),
    )

    # cib_clusters table
    op.create_table(
        "cib_clusters",
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
            "detected_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "member_event_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        sa.Column("member_count", sa.Integer, nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "severity",
            sa.Text,
            sa.CheckConstraint("severity IN ('medium','high')", name="ck_cib_severity"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_cib_clusters_project_detected",
        "cib_clusters",
        ["project_id", "detected_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_cib_clusters_project_detected", table_name="cib_clusters")
    op.drop_table("cib_clusters")
    op.drop_column("sources", "source_config")
    # Note: Postgres ENUM values cannot be removed in downgrade without DROP TYPE.
    # social_listening and narrative_op enum values are left in place on downgrade.
