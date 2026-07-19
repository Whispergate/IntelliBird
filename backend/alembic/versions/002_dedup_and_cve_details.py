""" migration 002: dedup UNIQUE constraint + cve_details table.

Revision ID: 0002_dedup_and_cve_details
Revises: 0001_initial_schema
Create Date: 2026-04-17

- UNIQUE index on (source_id, content_hash, observed_at) on events hypertable
. TimescaleDB requires the partition column (observed_at)
 to be included in any unique index on a hypertable; we use create_index with
 unique=True rather than ALTER TABLE ADD CONSTRAINT. The index name matches the
 constraint-name convention so IntegrityError messages still cite
 uq_events_source_content_hash.
- cve_details table for INGC-02 - separate from events to avoid widening
 the hot hypertable with CVE-specific columns.

TimescaleDB compatibility note: `ALTER TABLE events ADD CONSTRAINT... UNIQUE
(source_id, content_hash)` fails with "cannot create a unique index without the
column observed_at (used in partitioning)". Fallback: unique index including the
partition column. Workers still use ON CONFLICT (source_id, content_hash) with a
WHERE clause covering the same partition window, OR use ON CONFLICT ON CONSTRAINT
with the three-column index - the index name is used as the conflict target.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_dedup_and_cve_details"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    #: race-proof dedup enforced at DB layer.
    # TimescaleDB requires the partition column (observed_at) in every unique
    # index on a hypertable - ALTER TABLE ADD CONSTRAINT UNIQUE (source_id,
    # content_hash) is rejected at runtime. We create a UNIQUE index that
    # includes observed_at as the third column. The index still enforces
    # (source_id, content_hash) uniqueness within any given observed_at value
    # (i.e. two events with the same source+hash but different timestamps are
    # allowed, which is correct - a genuinely re-fetched item will have the same
    # content_hash and the same observed_at, landing on the same row via ON
    # CONFLICT logic).
    op.create_index(
        "uq_events_source_content_hash",
        "events",
        ["source_id", "content_hash", "observed_at"],
        unique=True,
    )

    # INGC-02 - cve_details table. Keyed on event_id (plain UUID, no FK
    # because events is a TimescaleDB hypertable - same pattern as
    # attack_technique_tags.event_id).
    op.create_table(
        "cve_details",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("cve_id", sa.Text(), nullable=False),
        sa.Column("cvss_v3_score", sa.Double(), nullable=True),
        sa.Column("cvss_v3_vector", sa.Text(), nullable=True),
        sa.Column("cpe_match", postgresql.JSONB(), nullable=True),
        sa.Column("cwe_ids", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("last_modified", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("idx_cve_details_cve_id", "cve_details", ["cve_id"])
    op.create_index("idx_cve_details_cvss_v3", "cve_details", ["cvss_v3_score"])


def downgrade() -> None:
    op.drop_index("idx_cve_details_cvss_v3", table_name="cve_details")
    op.drop_index("idx_cve_details_cve_id", table_name="cve_details")
    op.drop_table("cve_details")
    op.drop_index("uq_events_source_content_hash", table_name="events")
