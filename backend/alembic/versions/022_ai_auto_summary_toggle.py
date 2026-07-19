"""Per-project ai_auto_summary_enabled toggle.

Revision ID: 018_ai_auto_summary_toggle
Revises: 017_events_dedup_per_project
Create Date: 2026-05-02

Adds a per-project boolean controlling whether newly-ingested events are
automatically summarised by the Ollama worker. Off by default - bulk feeds
(e.g. NVD initial backfill, large STIX bundles) would otherwise queue
thousands of summary jobs and saturate the AI worker.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018_ai_auto_summary_toggle"
down_revision: Union[str, None] = "017_events_dedup_per_project"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "ai_auto_summary_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "ai_auto_summary_enabled")
