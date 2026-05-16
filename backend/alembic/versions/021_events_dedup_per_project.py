"""Per-project events dedup index + LEGACY backfill — Quick task 260429-tyq.

Revision ID: 017_events_dedup_per_project
Revises: 016_brand_stoplist
Create Date: 2026-04-29

Rationale
---------
Threading project_id through the RSS/NVD/TAXII ingest workers requires per-project
fan-out — a single source bound to N projects must produce N event rows, one per
project, all sharing (source_id, content_hash, observed_at). The original 3-column
unique index (source_id, content_hash, observed_at) created in migration 002 would
collapse those N rows into 1, defeating the binding model.

This migration:
  1. Drops the 3-column unique index `uq_events_source_content_hash`.
  2. Recreates it as a 4-column unique index with `project_id` FIRST for selectivity
     (most queries filter by project_id), then (source_id, content_hash, observed_at).
     Same index name preserved so worker ON CONFLICT clauses can be updated to the
     4-column tuple without renaming.
  3. Backfills existing LEGACY events (project_id = LEGACY_PROJECT_ID) into the
     project(s) currently bound via project_sources. Each LEGACY row becomes 0..N
     additional rows, one per binding. LEGACY copies are RETAINED — audit trail.

Index column order
------------------
project_id is placed first because:
  - Highest selectivity in practice (LEGACY-vs-project-N split is the dominant filter).
  - Worker ON CONFLICT clauses now key on (project_id, source_id, content_hash,
    observed_at), and Postgres can match an ON CONFLICT to a partial column-set even
    when ordering differs, but leading-column ordering reduces planner cost.

LEGACY retention
----------------
Backfill INSERTs new rows; it does NOT DELETE LEGACY originals. This preserves a
forensic record of what landed pre-binding and keeps any external references intact.
Re-running `alembic upgrade head` after binding more sources is safe — `ON CONFLICT
DO NOTHING` makes the backfill idempotent (re-runs only insert pairs that don't yet
exist).

TimescaleDB note
----------------
events is a hypertable partitioned on observed_at. Every unique index on the
hypertable MUST include observed_at — confirmed retained in the new 4-column index.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017_events_dedup_per_project"
down_revision: Union[str, None] = "016_brand_stoplist"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop the 3-column unique index
    op.drop_index("uq_events_source_content_hash", table_name="events")

    # 2. Recreate as 4-column unique index with project_id first
    op.create_index(
        "uq_events_source_content_hash",
        "events",
        ["project_id", "source_id", "content_hash", "observed_at"],
        unique=True,
    )

    # 3. Idempotent LEGACY backfill — copy LEGACY events into bound projects.
    # Column list mirrors app.models.events.Event. If a column is added later,
    # this list will be stale, but this is a one-shot backfill — re-running after
    # a future column addition will simply not propagate that column for the few
    # LEGACY-binding pairs that landed in between.
    op.execute(sa.text("""
        INSERT INTO events (
            id, stix_id, stix_type, source_id, project_id, fetched_at,
            raw_reference, observed_at, title, description, confidence,
            tlp_marking_id, content_hash, geo_lat, geo_lon, country_code,
            visibility, raw_stix, tags, archived, created_at,
            easm_scan_id, score, scored_at, score_version
        )
        SELECT
            gen_random_uuid(),
            e.stix_id, e.stix_type, e.source_id, ps.project_id, e.fetched_at,
            e.raw_reference, e.observed_at, e.title, e.description, e.confidence,
            e.tlp_marking_id, e.content_hash, e.geo_lat, e.geo_lon, e.country_code,
            e.visibility, e.raw_stix, e.tags, e.archived, e.created_at,
            e.easm_scan_id, e.score, e.scored_at, e.score_version
        FROM events e
        JOIN project_sources ps ON ps.source_id = e.source_id
        WHERE e.project_id = '00000000-0000-0000-0000-000000000001'
        ON CONFLICT (project_id, source_id, content_hash, observed_at) DO NOTHING
    """))


def downgrade() -> None:
    # Schema-only reversal. Backfill rows are data — left in place. If reverting
    # is required and the duplicates are unwanted, run a manual cleanup:
    #   DELETE FROM events WHERE project_id <> LEGACY_PROJECT_ID
    #     AND (source_id, content_hash, observed_at) IN (
    #       SELECT source_id, content_hash, observed_at
    #       FROM events WHERE project_id = LEGACY_PROJECT_ID);
    op.drop_index("uq_events_source_content_hash", table_name="events")
    op.create_index(
        "uq_events_source_content_hash",
        "events",
        ["source_id", "content_hash", "observed_at"],
        unique=True,
    )
