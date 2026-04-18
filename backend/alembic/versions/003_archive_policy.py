"""Phase 3 migration 003: archive_policy enum + silent_failure_count counter.

Revision ID: 0003_archive_policy
Revises: 0002_dedup_and_cve_details
Create Date: 2026-04-17

- archive_policy_enum: new PostgreSQL enum type with values ('keep', 'drop', 'move-to-cold').
  Created idempotently via DO $$ ... EXCEPTION WHEN duplicate_object THEN NULL $$ to tolerate
  partial/repeat upgrades. (Pitfall 5 — CREATE TYPE is not idempotent.)
- sources.archive_policy: enum column, NOT NULL, server_default 'drop'.
  Matches the archive_policy field in SourceCreate / SourceUpdate payloads (Plan 02).
  Archiver (Plan 05) switches per-source on this column.
- sources.silent_failure_count: Integer, NOT NULL, server_default 0.
  Incremented in app.ingest.normalise / app.services.source_health (Plan 04) when a
  successful poll inserts zero new rows; reset to 0 on any successful insert.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_archive_policy"
down_revision: Union[str, None] = "0002_dedup_and_cve_details"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Pitfall 5 — idempotent enum creation
    op.execute(
        "DO $$ BEGIN "
        "  CREATE TYPE archive_policy_enum AS ENUM ('keep', 'drop', 'move-to-cold'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )
    op.add_column(
        "sources",
        sa.Column(
            "archive_policy",
            sa.Enum(
                "keep", "drop", "move-to-cold",
                name="archive_policy_enum",
                create_type=False,  # created by the DO block above
            ),
            nullable=False,
            server_default="drop",
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "silent_failure_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("sources", "silent_failure_count")
    op.drop_column("sources", "archive_policy")
    op.execute("DROP TYPE IF EXISTS archive_policy_enum")
