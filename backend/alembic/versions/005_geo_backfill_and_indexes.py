"""005 Partial geo index on events - MAP-05.

Revision ID: 005_geo_backfill_and_indexes
Revises: 004_fts_and_presets
Create Date: 2026-04-17

Adds a partial B-tree index on events(geo_lat, geo_lon) restricted to rows
where geo_lat IS NOT NULL AND geo_lon IS NOT NULL. Only rows that carry
resolved geo coordinates enter the index - keeps it small while making the
 has_geo filter (WHERE geo_lat IS NOT NULL AND geo_lon IS NOT NULL)
an index-scan rather than a seq-scan over the full hypertable.

Note: TimescaleDB hypertables do NOT support CREATE INDEX CONCURRENTLY.
Use standard (non-concurrent) index creation inside the migration transaction.
CONCURRENTLY is only needed for live-traffic production tables; M1 self-hosted
stack has no concurrent writes during migration.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "005_geo_backfill_and_indexes"
down_revision: Union[str, None] = "004_fts_and_presets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # TimescaleDB hypertables do not support CONCURRENTLY - use standard CREATE INDEX.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_geo_coords "
        "ON events (geo_lat, geo_lon) "
        "WHERE geo_lat IS NOT NULL AND geo_lon IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS idx_events_geo_coords"
    )
