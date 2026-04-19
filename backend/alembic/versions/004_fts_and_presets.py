"""004 FTS tsvector generated column + filter_presets table

Revision ID: 004_fts_and_presets
Revises: 003_archive_policy
Create Date: 2026-04-17

Adds events.search_tsv STORED GENERATED column + GIN index (FIL-05).
Adds filter_presets table (FIL-04).

TimescaleDB note: ALTER TABLE... ADD COLUMN... GENERATED ALWAYS AS... STORED
triggers a backfill over all existing chunks. Non-concurrent; accept block on
bootstrapped datasets. (CREATE INDEX CONCURRENTLY in a txn) NOT used
here — standard CREATE INDEX propagates to chunks via TimescaleDB 2.x.

Name check constraint: ^[a-z0-9_-]{1,64}$ applied on filter_presets.name.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "004_fts_and_presets"
down_revision: Union[str, None] = "0003_archive_policy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # FIL-05: search_tsv generated column on events hypertable
    # GENERATED ALWAYS AS STORED triggers backfill on all existing chunks.
    # Standard (non-CONCURRENTLY) CREATE INDEX propagates to all TimescaleDB chunks.
    op.execute(
        """
 ALTER TABLE events
 ADD COLUMN IF NOT EXISTS search_tsv tsvector
 GENERATED ALWAYS AS (
 to_tsvector('english',
 COALESCE(title, '') || ' ' ||
 COALESCE(description, '') || ' ' ||
 COALESCE(raw_stix->>'description', '') || ' ' ||
 COALESCE(raw_stix->>'name', ''))
 ) STORED
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_events_search_tsv "
        "ON events USING GIN (search_tsv)"
    )

    # FIL-04: filter_presets table
    # name CHECK constraint enforces ^[a-z0-9_-]{1,64}$ at DB level.
    op.execute(
        """
 CREATE TABLE IF NOT EXISTS filter_presets (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid,
 name text NOT NULL UNIQUE,
 query_params jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now,
 updated_at timestamptz NOT NULL DEFAULT now,
 CONSTRAINT filter_presets_name_check
 CHECK (name ~ '^[a-z0-9_-]{1,64}$')
 )
"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS filter_presets")
    op.execute("DROP INDEX IF EXISTS ix_events_search_tsv")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS search_tsv")
