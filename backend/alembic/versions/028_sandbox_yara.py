"""028 - sandbox_configs, sandbox_reports hypertable, yara_rules, yara_matches.

SANDBOX-01, SANDBOX-03, SANDBOX-04, YARA-01, YARA-02.

Creates four tables that form the foundation for the sandbox detonation and YARA
scanning subsystems.

  sandbox_configs       Per-project provider config (one row per project, unique).
  sandbox_reports       TimescaleDB hypertable partitioned on submitted_at - holds
                        full detonation results, polling state, extracted techniques.
  yara_rules            Global or per-project YARA rule store with compiled bytea cache.
  yara_matches          M2M join between yara_rules and events (SOFT FK on event_id).

Design notes:
  * sandbox_reports.event_id is a SOFT FK (no REFERENCES clause) - events is a
    TimescaleDB hypertable; real FK constraints are not supported against hypertables.
    Nullable because a report may be triggered from an IOC that has no event link.
  * yara_matches.event_id is also a SOFT FK for the same reason.
  * sandbox_reports uses a composite PRIMARY KEY (id, submitted_at) as required by
    TimescaleDB for hypertables.
  * Retention policy: 365 days on sandbox_reports (full reports are large; old ones
    can be reconstructed from provider on demand).
  * poll_attempts is load-bearing for SANDBOX-03 timeout / back-off logic.
  * downgrade() drops tables in reverse dependency order.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "028_sandbox_yara"
down_revision: Union[str, None] = "027_taxii_clients"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. sandbox_configs - per-project provider configuration
    # ------------------------------------------------------------------
    op.execute("""
CREATE TABLE sandbox_configs (
    id              uuid        NOT NULL DEFAULT gen_random_uuid(),
    project_id      uuid        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    provider        text        NOT NULL,
    api_key_enc     text        NULL,
    enabled         boolean     NOT NULL DEFAULT false,
    public_warning_acknowledged boolean NOT NULL DEFAULT false,
    options         jsonb       NOT NULL DEFAULT '{}',
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    UNIQUE (project_id)
);
""")

    # ------------------------------------------------------------------
    # 2. sandbox_reports - TimescaleDB hypertable (partition on submitted_at)
    #
    # Composite PK (id, submitted_at) required by TimescaleDB - the partition
    # column must appear in all unique constraints.
    #
    # event_id is a SOFT FK: events is a hypertable; real FK not supported.
    # Nullable because the submission may come from a bare IOC without an event link.
    # ------------------------------------------------------------------
    op.execute("""
CREATE TABLE sandbox_reports (
    id              uuid        NOT NULL DEFAULT gen_random_uuid(),
    submitted_at    timestamptz NOT NULL DEFAULT now(),
    event_id        uuid        NULL,         -- SOFT FK: events is a hypertable, real FK not supported; nullable when IOC has no event link
    project_id      uuid        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    provider        text        NOT NULL,
    job_id          text        NULL,
    status          text        NOT NULL DEFAULT 'pending',
    sha256          text        NOT NULL,
    report_json     jsonb       NULL,
    techniques      text[]      NULL,
    network_iocs    jsonb       NULL,
    process_tree    jsonb       NULL,
    score           int         NULL,
    verdict         text        NULL,
    error_detail    text        NULL,
    completed_at    timestamptz NULL,
    poll_attempts   int         NOT NULL DEFAULT 0,
    PRIMARY KEY (id, submitted_at)
);
""")
    op.execute("SELECT create_hypertable('sandbox_reports', 'submitted_at', if_not_exists => TRUE);")
    op.execute("SELECT add_retention_policy('sandbox_reports', INTERVAL '365 days', if_not_exists => TRUE);")
    op.execute("CREATE INDEX ix_sandbox_reports_event_id ON sandbox_reports (event_id);")
    op.execute("CREATE INDEX ix_sandbox_reports_project_id ON sandbox_reports (project_id);")

    # ------------------------------------------------------------------
    # 3. yara_rules - global or per-project YARA rule store
    #
    # NULL project_id = global rule visible to all projects (admin-curated).
    # compiled_cache stores pre-compiled bytea to avoid recompile on every scan.
    # ------------------------------------------------------------------
    op.execute("""
CREATE TABLE yara_rules (
    id              uuid        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    name            text        NOT NULL,
    family          text        NOT NULL DEFAULT '',
    content         text        NOT NULL,
    compiled_cache  bytea       NULL,
    enabled         boolean     NOT NULL DEFAULT true,
    project_id      uuid        NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
""")

    # ------------------------------------------------------------------
    # 4. yara_matches - M2M between yara_rules and events
    #
    # event_id is a SOFT FK: events is a hypertable, real FK not supported.
    # scan_context distinguishes file-sample scans from STIX-pattern matches.
    # UNIQUE (rule_id, event_id, scan_context) prevents duplicate match records.
    # ------------------------------------------------------------------
    op.execute("""
CREATE TABLE yara_matches (
    id              uuid        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    rule_id         uuid        NOT NULL REFERENCES yara_rules(id) ON DELETE CASCADE,
    event_id        uuid        NOT NULL,   -- SOFT FK: events is a hypertable, real FK not supported
    matched_at      timestamptz NOT NULL DEFAULT now(),
    match_strings   jsonb       NULL,
    scan_context    text        NOT NULL DEFAULT 'sample',   -- 'sample' | 'stix_pattern'
    UNIQUE (rule_id, event_id, scan_context)
);
""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS yara_matches;")
    op.execute("DROP TABLE IF EXISTS yara_rules;")
    op.execute("DROP TABLE IF EXISTS sandbox_reports;")
    op.execute("DROP TABLE IF EXISTS sandbox_configs;")
