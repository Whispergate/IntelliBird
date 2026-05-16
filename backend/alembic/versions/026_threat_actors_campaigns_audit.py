"""026 — threat_actors, campaigns, campaign_events, actor_event_links, audit_log hypertable.

Phase 25 / ACTOR-01, ACTOR-03, AUDIT-01, AUDIT-02.

Creates five new tables that form the foundation for the threat-actor/campaign
management subsystem and the audit log.

  threat_actors         Global actor registry (MITRE ATT&CK groups + analyst-curated).
  campaigns             Campaign records optionally linked to an actor and a project.
  campaign_events       M2M junction: campaign ↔ event (SOFT FK — events is hypertable).
  actor_event_links     Auto-link table from fuzzy-name match (rapidfuzz ≥85 score).
  audit_log             Append-only hypertable (TimescaleDB) — 365-day retention policy.
                        Composite PK (time, id) — TimescaleDB requires partition column
                        in all unique constraints.

Design notes:
  * campaign_events.event_id and actor_event_links.event_id are SOFT FKs (no REFERENCES
    clause) because events is a TimescaleDB hypertable; real FK constraints are not
    supported against hypertables.
  * country, motivation, sophistication are NOT standard STIX fields. They are nullable,
    analyst-editable only.
  * audit_log uses SELECT create_hypertable(...) + SELECT add_retention_policy(...)
    matching the precedent in migration 016_monitoring.
  * downgrade() drops tables in reverse dependency order to avoid FK violations.

TimescaleDB extension is already loaded by migration 001 — no CREATE EXTENSION needed.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "026_actors_campaigns_audit"
down_revision: Union[str, None] = "025_darkweb_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. threat_actors — global actor registry
    # ------------------------------------------------------------------
    op.execute("""
CREATE TABLE threat_actors (
    id                  uuid        NOT NULL DEFAULT gen_random_uuid(),
    primary_name        text        NOT NULL,
    aliases             text[]      NULL,
    country             text        NULL,
    motivation          text        NULL,
    sophistication      text        NULL,
    first_seen          timestamptz NULL,
    profile_md          text        NULL,
    mitre_group_id      text        NULL,
    last_bootstrap_at   timestamptz NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
""")
    # Partial unique index — mitre_group_id must be unique when non-NULL.
    # A full UNIQUE constraint would allow at most one NULL row in some PG versions;
    # a partial index allows unlimited NULLs while enforcing uniqueness among real values.
    op.execute("""
CREATE UNIQUE INDEX uq_threat_actors_mitre_group_id
    ON threat_actors (mitre_group_id)
    WHERE mitre_group_id IS NOT NULL;
""")

    # ------------------------------------------------------------------
    # 2. campaigns — per-project or global campaign records
    # ------------------------------------------------------------------
    op.execute("""
CREATE TABLE campaigns (
    id                  uuid        NOT NULL DEFAULT gen_random_uuid(),
    name                text        NOT NULL,
    actor_id            uuid        NULL REFERENCES threat_actors(id) ON DELETE SET NULL,
    start_date          date        NULL,
    end_date            date        NULL,
    summary_md          text        NULL,
    project_id          uuid        NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_by_user_sub text        NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
""")
    op.execute("CREATE INDEX idx_campaigns_actor_id   ON campaigns (actor_id);")
    op.execute("CREATE INDEX idx_campaigns_project_id ON campaigns (project_id);")

    # ------------------------------------------------------------------
    # 3. campaign_events — M2M junction (SOFT FK on event_id)
    # ------------------------------------------------------------------
    op.execute("""
CREATE TABLE campaign_events (
    campaign_id         uuid        NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    event_id            uuid        NOT NULL,   -- soft FK: events is a hypertable
    linked_by_user_sub  text        NULL,
    linked_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (campaign_id, event_id)
);
""")
    op.execute("CREATE INDEX idx_campaign_events_event_id ON campaign_events (event_id);")

    # ------------------------------------------------------------------
    # 4. actor_event_links — auto-link from fuzzy-name match (≥85 score)
    # ------------------------------------------------------------------
    op.execute("""
CREATE TABLE actor_event_links (
    actor_id    uuid        NOT NULL REFERENCES threat_actors(id) ON DELETE CASCADE,
    event_id    uuid        NOT NULL,   -- soft FK: events is a hypertable
    linked_at   timestamptz NOT NULL DEFAULT now(),
    linked_by   text        NOT NULL DEFAULT 'auto',
    PRIMARY KEY (actor_id, event_id)
);
""")
    op.execute("CREATE INDEX idx_actor_event_links_event_id ON actor_event_links (event_id);")

    # ------------------------------------------------------------------
    # 5. audit_log — append-only hypertable
    # Composite PK (time, id): TimescaleDB requires the partition column to
    # appear in all unique constraints (same pattern as events (observed_at, id)).
    # ------------------------------------------------------------------
    op.execute("""
CREATE TABLE audit_log (
    id              uuid        NOT NULL DEFAULT gen_random_uuid(),
    time            timestamptz NOT NULL DEFAULT now(),
    user_sub        text        NULL,
    action          text        NOT NULL,
    resource_type   text        NOT NULL,
    resource_id     text        NULL,
    project_id      uuid        NULL REFERENCES projects(id) ON DELETE SET NULL,
    before_jsonb    jsonb       NULL,
    after_jsonb     jsonb       NULL,
    request_id      text        NULL,
    PRIMARY KEY (time, id)
);
""")
    op.execute("CREATE INDEX idx_audit_log_resource ON audit_log (resource_type, resource_id);")
    op.execute("CREATE INDEX idx_audit_log_user_sub ON audit_log (user_sub);")

    # Convert audit_log to TimescaleDB hypertable and add 365-day retention policy.
    # if_not_exists guards are idempotent — safe to re-run.
    op.execute("SELECT create_hypertable('audit_log', 'time', if_not_exists => TRUE);")
    op.execute(
        "SELECT add_retention_policy('audit_log', INTERVAL '365 days', if_not_exists => TRUE);"
    )


def downgrade() -> None:
    # Drop in reverse dependency order to avoid FK violations.
    op.execute("DROP TABLE IF EXISTS actor_event_links;")
    op.execute("DROP TABLE IF EXISTS campaign_events;")
    op.execute("DROP TABLE IF EXISTS campaigns;")
    op.execute("DROP TABLE IF EXISTS audit_log;")
    op.execute("DROP TABLE IF EXISTS threat_actors;")
