"""monitoring infrastructure - hypertable + CA + maintenance windows + sources columns
+ webhook_alert_type_enum + sentinel project.

Revision ID: 016_monitoring
Revises: 013_scoring
Create Date: 2026-04-25

MON-01, MON-02, MON-03, MON-05.

Schema foundation for the continuous monitoring subsystem:

  sources.last_event_at timestamptz NULL
    MON-01: SLA-based silence detection compares now() - last_event_at against per-source SLA
    threshold (resolved from monitoring_config or DEFAULT_SLA_BY_FEED_TYPE). Updated by all 4
    ingest sites (normalise.py, nvd.py, brand_monitor.py, easm.py) after successful insert.

  sources.monitoring_config jsonb NOT NULL DEFAULT '{}'::jsonb
    MON-02/03: per-source drift and parse-error-rate thresholds. Schema validated by
    app.schemas.monitoring.MonitoringConfig; empty {} means "use feed_type defaults".

  maintenance_windows table
    H-7: global maintenance window suppresses all MON-01..03 alerts.
    is_maintenance_active() checks now() BETWEEN start_at AND end_at on the indexed range.

  source_ingest_stats hypertable
    MON-03: item-level parse_ok/parse_error + batch fetch_ok/fetch_error counters. Single INSERT
    per source at end of each poll batch (record_ingest_stats helper in source_health.py).
    TimescaleDB create_hypertable partitions by 'time'. 90d retention policy applied.

  source_ingest_stats_hourly continuous aggregate (CA)
    MON-02: drift z-score reads 168 hourly buckets × N sources. Refresh every 1h.
    First use of TimescaleDB continuous aggregate in this project - WITH NO DATA required
    (Pitfall: omitting NO DATA causes CA materialisation failure on empty hypertable in some
    TimescaleDB 2.x versions; defensive approach: always use WITH NO DATA + explicit policy).

  webhook_alert_type_enum with values source_silence, volume_drift, parse_error_rate
    MON-05: monitoring_synth.py emits canonical events with these alert types; existing webhook
    fan-out picks them up without any new webhook code (BRP-05 precedent).
    Confirmed by grep on migrations 001..015: webhook_alert_type_enum does NOT exist yet.
    DO $$ EXCEPTION WHEN duplicate_object pattern (Pitfall 1 - idempotent ENUM creation per
    migration 003/006/009 precedent).

  Sentinel project row 00000000-0000-0000-0000-000000000000
    Pitfall 3 - events.project_id is NOT NULL (added by migration 009). Any monitoring event
    inserted by monitoring_synth.py must carry a valid project_id. The sentinel project
    'system-monitoring' satisfies that FK constraint without exposing monitoring events to
    normal project queries (archived=true, intel_only engagement type).
    Note: migration 009 uses LEGACY_PROJECT_ID = 00000000-0000-0000-0000-000000000001.
    The monitoring sentinel uses ...0000 (all zeros), distinct from the legacy sentinel.

TimescaleDB extension is already loaded by migration 001 (Pitfall 2 - no CREATE EXTENSION
call needed here; add_retention_policy and create_hypertable are available from 001 onward).

ADD COLUMN safety (migration 013 precedent): sources is NOT a hypertable (it is a plain
PostgreSQL table), so the split-statement requirement does NOT apply. However, we still use
separate op.execute() calls per logical block for clarity and consistency.

No CONCURRENT index creation anywhere in this migration - standard CREATE INDEX is used
throughout (consistent with all prior migrations; concurrent form is rejected by TimescaleDB
in a transaction on compressed hypertables).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "016_monitoring"
down_revision: Union[str, None] = "013_scoring"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. sources.last_event_at timestamptz NULL ----------------------------------
    # MON-01: silence detection pivot column. Nullable - NULL means "no event ever
    # received" which is itself a silence signal. Updated by all 4 ingest sites
    # (normalise.py, nvd.py, brand_monitor.py, easm.py) after successful insert.
    # sources is a plain PG table (not a hypertable) - single-statement ALTER is safe.
    op.execute("ALTER TABLE sources ADD COLUMN last_event_at timestamptz NULL;")

    # --- 2. sources.monitoring_config jsonb NOT NULL DEFAULT '{}' -------------------
    # MON-02/03: per-source threshold overrides. Empty JSONB {} means "use feed_type
    # defaults" (resolved by MonitoringConfig.model_validate({}) in monitoring.py).
    # NOT NULL with DEFAULT allows backfill of existing rows without a separate UPDATE.
    op.execute(
        "ALTER TABLE sources ADD COLUMN monitoring_config jsonb NOT NULL DEFAULT '{}'::jsonb;"
    )

    # --- 3. maintenance_windows table -----------------------------------------------
    # H-7: global-only maintenance window. created_by_user_id nullable - rows inserted
    # programmatically (e.g., API bootstrap) don't always have a user context.
    # ON DELETE SET NULL so window records survive user deletion (audit trail).
    # No slug or project scope - one window suppresses ALL monitoring alerts globally.
    op.execute(
        """
        CREATE TABLE maintenance_windows (
            id                  uuid        NOT NULL DEFAULT gen_random_uuid(),
            start_at            timestamptz NOT NULL,
            end_at              timestamptz NOT NULL,
            created_by_user_id  uuid        NULL REFERENCES users(id) ON DELETE SET NULL,
            reason              text        NULL,
            created_at          timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (id)
        );
        """
    )

    # --- 4. Index on maintenance_windows (start_at, end_at) -------------------------
    # is_maintenance_active() query: now() BETWEEN start_at AND end_at → index both
    # columns to support the range predicate efficiently.
    op.execute("CREATE INDEX ix_mw_range ON maintenance_windows (start_at, end_at);")

    # --- 5. source_ingest_stats table -----------------------------------------------
    # MON-03: item-level ingest counters. Primary key (time, source_id) is required
    # before create_hypertable - TimescaleDB promotes time to the partitioning dimension.
    # ON DELETE CASCADE ensures orphan stats rows are purged when a source is removed.
    op.execute(
        """
        CREATE TABLE source_ingest_stats (
            time         timestamptz NOT NULL,
            source_id    uuid        NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            parse_ok     int         NOT NULL DEFAULT 0,
            parse_error  int         NOT NULL DEFAULT 0,
            fetch_ok     int         NOT NULL DEFAULT 0,
            fetch_error  int         NOT NULL DEFAULT 0,
            PRIMARY KEY (time, source_id)
        );
        """
    )

    # --- 6. create_hypertable on source_ingest_stats --------------------------------
    # Pitfall 2: TimescaleDB extension is already loaded by migration 001; no CREATE
    # EXTENSION call needed here. if_not_exists=TRUE is a safety net for idempotency
    # (idempotent per TimescaleDB docs for create_hypertable since 2.x).
    op.execute(
        "SELECT create_hypertable('source_ingest_stats', 'time', if_not_exists => TRUE);"
    )

    # --- 7. 90-day retention policy on source_ingest_stats --------------------------
    # MON-03: 90d hot tier matches the source health audit window. TimescaleDB
    # add_retention_policy schedules automatic chunk drop via TimescaleDB background
    # worker (no custom cron needed). INTERVAL '90 days' is the project-locked value
    # from 16-CONTEXT.md §source_ingest_stats hypertable schema.
    op.execute(
        "SELECT add_retention_policy('source_ingest_stats', INTERVAL '90 days');"
    )

    # --- 8. source_ingest_stats_hourly continuous aggregate (CA) --------------------
    # MON-02: drift z-score queries 168 hourly buckets × N sources. CA materialises the
    # aggregation so drift checks are cheap SELECT queries rather than full hypertable scans.
    # WITH NO DATA is mandatory here (Pitfall: omitting NO DATA can fail on empty hypertable
    # in some TimescaleDB 2.x versions; always use WITH NO DATA + explicit refresh policy).
    # First use of timescaledb.continuous in this project - CREATE MATERIALIZED VIEW with
    # the timescaledb.continuous option converts the view into a managed CA.
    op.execute(
        """
        CREATE MATERIALIZED VIEW source_ingest_stats_hourly
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 hour', time) AS bucket,
            source_id,
            SUM(parse_ok)    AS parse_ok,
            SUM(parse_error) AS parse_error,
            SUM(fetch_ok)    AS fetch_ok,
            SUM(fetch_error) AS fetch_error
        FROM source_ingest_stats
        GROUP BY bucket, source_id
        WITH NO DATA;
        """
    )

    # --- 9. Continuous aggregate refresh policy -------------------------------------
    # Refresh every 1h, materialise from 7d ago to 1h ago (end_offset keeps the
    # "real-time window" unbucketed so the CA doesn't overwrite in-progress hour).
    # schedule_interval='1 hour' aligns with bucket size - one sweep per bucket boundary.
    op.execute(
        """
        SELECT add_continuous_aggregate_policy(
            'source_ingest_stats_hourly',
            start_offset      => INTERVAL '7 days',
            end_offset        => INTERVAL '1 hour',
            schedule_interval => INTERVAL '1 hour'
        );
        """
    )

    # --- 10. webhook_alert_type_enum ------------------------------------------------
    # MON-05: monitoring_synth.py emits events with alert_type from this enum; existing
    # webhook fan-out (webhook_dispatcher.py) handles dispatch with zero new webhook code.
    # DO $$ EXCEPTION WHEN duplicate_object pattern (Pitfall 1 - established project
    # pattern from migrations 003, 006, 008, 009): if a partial upgrade already created
    # the type, the EXCEPTION branch adds any missing values via ALTER TYPE ... ADD VALUE
    # IF NOT EXISTS (PG 10+ supports conditional ADD VALUE; safe no-op if value exists).
    # Confirmed by grep on all prior migrations: webhook_alert_type_enum does NOT exist.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE webhook_alert_type_enum AS ENUM (
                'source_silence',
                'volume_drift',
                'parse_error_rate'
            );
        EXCEPTION WHEN duplicate_object THEN
            -- Partial migration re-run: ensure all values are present.
            -- PG cannot DROP ENUM values so we only ADD IF NOT EXISTS.
            ALTER TYPE webhook_alert_type_enum ADD VALUE IF NOT EXISTS 'source_silence';
            ALTER TYPE webhook_alert_type_enum ADD VALUE IF NOT EXISTS 'volume_drift';
            ALTER TYPE webhook_alert_type_enum ADD VALUE IF NOT EXISTS 'parse_error_rate';
        END $$;
        """
    )

    # --- 11. Sentinel project row for monitoring events -----------------------------
    # Pitfall 3: events.project_id is NOT NULL (migration 009 three-step backfill).
    # monitoring_synth.py inserts canonical event rows with project_id set to this UUID
    # so the NOT NULL + FK constraint is satisfied without associating monitoring events
    # with any real analyst project. archived=true keeps it out of normal project lists.
    # engagement_type='intel_only' is the closest semantic match for system-level events.
    # ON CONFLICT (id) DO NOTHING - idempotent; safe to run on an existing install.
    # Sentinel project UUID (locked from 16-02-PLAN.md interfaces block):
    #   00000000-0000-0000-0000-000000000000  (all zeros)
    # DISTINCT from the legacy sentinel 00000000-0000-0000-0000-000000000001 (mig 009).
    # Webhook subscriptions for this project receive monitoring alerts.
    op.execute(
        """
        INSERT INTO projects
          (id, name, engagement_type, description, created_by, archived, active_scans_authorised)
        VALUES
          ('00000000-0000-0000-0000-000000000000'::uuid,
           'System Monitoring',
           'intel_only',
           'Sentinel project for monitoring/system events; satisfies events.project_id NOT NULL constraint (mig 009). Webhook subscriptions for this project receive monitoring alerts.',
           'system',
           true,
           false)
        ON CONFLICT (id) DO NOTHING;
        """
    )


def downgrade() -> None:
    # Reverse in strict opposite order of upgrade().
    # NOTE: webhook_alert_type_enum values cannot be dropped (PG limitation -
    # ALTER TYPE DROP VALUE does not exist in PostgreSQL). The ENUM type itself is
    # dropped below, but if any column references it the DROP TYPE will fail with
    # a dependency error; that is the expected safety gate.

    # --- 11. Remove sentinel project row -------------------------------------------
    op.execute(
        "DELETE FROM projects WHERE id = '00000000-0000-0000-0000-000000000000'::uuid;"
    )

    # --- 10. Drop webhook_alert_type_enum -------------------------------------------
    # PG cannot DROP individual ENUM values; we drop the entire type.
    # If any column already references this type, the DROP TYPE will fail (intended -
    # means the downgrade is running after later migrations that added a column).
    op.execute("DROP TYPE IF EXISTS webhook_alert_type_enum;")

    # --- 9 + 8. Drop CA (automatically drops the refresh policy with CASCADE) -------
    op.execute("DROP MATERIALIZED VIEW IF EXISTS source_ingest_stats_hourly CASCADE;")

    # --- 7. Retention policy is dropped automatically when the hypertable is dropped.
    # TimescaleDB removes associated policies when the hypertable is dropped CASCADE.

    # --- 6 + 5. Drop source_ingest_stats (hypertable + all chunks) ------------------
    op.execute("DROP TABLE IF EXISTS source_ingest_stats CASCADE;")

    # --- 4 + 3. Drop maintenance_windows table and its index -----------------------
    op.execute("DROP INDEX IF EXISTS ix_mw_range;")
    op.execute("DROP TABLE IF EXISTS maintenance_windows;")

    # --- 2. Drop sources.monitoring_config ------------------------------------------
    op.execute("ALTER TABLE sources DROP COLUMN IF EXISTS monitoring_config;")

    # --- 1. Drop sources.last_event_at ----------------------------------------------
    op.execute("ALTER TABLE sources DROP COLUMN IF EXISTS last_event_at;")
