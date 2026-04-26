"""ai infrastructure tables (Phase 17 / AI-01..03, SCR-04)

Revision ID: 014_ai
Revises: 017_html_scrape
Create Date: 2026-04-25

(Filename 018_ai.py reflects insertion order; revision id remains "014_ai"
because models/tests reference that id. Originally branched off 013_scoring,
re-parented to 017_html_scrape after rebase to keep alembic head linear.)

Phase 17 / AI-01, AI-02, AI-03, SCR-04.

Schema foundation for the AI subsystem:

  ai_providers table
    AI-01: per-project LLM provider configuration. One row per project (UNIQUE on
    project_id). Stores provider_type (ollama/openai/anthropic), model_name, api_base
    (Ollama endpoint; NULL for hosted providers), and AES-256-GCM encrypted credentials
    in credentials_enc + credentials_key_version — exact mirror of sources.credentials_enc
    pattern from migration 007_credentials_key_version. project_id FK ondelete=CASCADE.

  ai_summaries table
    AI-02: LLM-generated summaries for individual events (summary_type='event') and
    daily project digests (summary_type='digest'). event_id is a soft UUID (no FK
    constraint to events.id) — events is a TimescaleDB hypertable and CANNOT be a FK
    target (same pattern as event_score_overrides.event_id in migration 013, and
    brand_matches.event_id in migration 011, and attack_technique_tags.event_id in
    migration 001). project_id FK ondelete=CASCADE for hard project scope.

  ai_suggestions table
    AI-03: analyst-gated entity extraction staging table. LLM proposes CVE IDs,
    ATT&CK technique IDs, or threat-actor names; analyst confirms or discards.
    ai_summary_id FK (CASCADE) links back to the summary that generated the suggestion.
    event_id is also a soft UUID column (no FK to hypertable). project_id FK for scope.
    status ENUM: pending → confirmed | discarded. decided_at + decided_by_user_id FK
    record the analyst decision (SET NULL on user delete for audit trail).

  events.ai_score numeric(5,2) NULL
    SCR-04: AI reranking stores per-event clamp result (rule_score ± 15). Read path:
    COALESCE(ai_score, score) — ai_score when AI rerank is enabled and present, else
    rule-computed score from migration 013. INSERT-only at scoring time per migration 013
    precedent — no UPDATE on compressed chunks.

  projects.ai_* columns
    ai_digest_enabled bool default false — opt-in daily digest generation
    ai_rerank_enabled bool default false — opt-in AI reranking pass
    ai_daily_token_cap int default 100000 — per-project token budget cap
    digest_schedule_cron text default '0 6 * * *' — APScheduler cron expression

ADD COLUMN safety (from migration 013 precedent):
  events is a TimescaleDB hypertable with columnstore. Each ADD COLUMN is its own
  op.execute() statement — required to avoid FeatureNotSupportedError on compressed
  hypertables. ai_score is nullable with no FK or NOT NULL constraint — safe as a
  single statement.

  projects is a plain PostgreSQL table — standard op.add_column() is safe.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014_ai"
down_revision: Union[str, None] = "017_html_scrape"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. ENUM types ---------------------------------------------------------------
    # DO $$ EXCEPTION WHEN duplicate_object pattern (idempotent per project convention
    # from migrations 003, 006, 009, 016): safe to re-run after partial upgrade.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE ai_provider_type_enum AS ENUM ('ollama', 'openai', 'anthropic');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE ai_summary_type_enum AS ENUM ('event', 'digest');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE ai_suggestion_type_enum AS ENUM ('cve', 'attack', 'actor');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE ai_suggestion_status_enum AS ENUM ('pending', 'confirmed', 'discarded');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    # --- 2. ai_providers table -------------------------------------------------------
    # One row per project (UNIQUE project_id). credentials_enc + credentials_key_version
    # mirror sources.credentials_enc pattern exactly (migration 007_credentials_key_version).
    # project_id FK ondelete=CASCADE — provider config is scoped to project lifetime.
    # api_base is NULL for hosted providers (OpenAI / Anthropic); required for Ollama.
    op.execute(
        """
        CREATE TABLE ai_providers (
            id                      uuid        NOT NULL DEFAULT gen_random_uuid(),
            project_id              uuid        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            provider_type           ai_provider_type_enum NOT NULL,
            model_name              text        NOT NULL,
            api_base                text        NULL,
            credentials_enc         text        NULL,
            credentials_key_version integer     NOT NULL DEFAULT 1,
            created_at              timestamptz NOT NULL DEFAULT now(),
            updated_at              timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (id),
            CONSTRAINT uq_ai_providers_project_id UNIQUE (project_id)
        );
        """
    )

    # --- 3. ai_summaries table -------------------------------------------------------
    # event_id is a soft UUID (NO FK CONSTRAINT) — events is a hypertable and cannot
    # be a FK target. Same pattern as event_score_overrides (migration 013) and
    # brand_matches (migration 011). Digests have event_id=NULL (summary_type='digest').
    # project_id FK ondelete=CASCADE enforces hard project scope (PROD-01 surface).
    op.execute(
        """
        CREATE TABLE ai_summaries (
            id                      uuid        NOT NULL DEFAULT gen_random_uuid(),
            project_id              uuid        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            event_id                uuid        NULL,
            summary_type            ai_summary_type_enum NOT NULL,
            provider_used           text        NOT NULL,
            model_used              text        NOT NULL,
            prompt_template_version text        NOT NULL,
            summary_text            text        NOT NULL,
            tokens_used             integer     NOT NULL DEFAULT 0,
            requires_analyst_review boolean     NOT NULL DEFAULT true,
            created_at              timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (id)
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_ai_summaries_project_id_created_at ON ai_summaries (project_id, created_at);"
    )
    op.execute(
        "CREATE INDEX ix_ai_summaries_event_id ON ai_summaries (event_id);"
    )

    # --- 4. ai_suggestions table -----------------------------------------------------
    # ai_summary_id FK (CASCADE) — suggestions are children of a summary; deleting the
    # summary purges its suggestions. project_id FK (CASCADE) adds a direct project scope
    # column for efficient filtering without joining through ai_summaries.
    # event_id is also a soft UUID (no FK to hypertable) for the same reason as
    # ai_summaries.event_id. decided_by_user_id FK (SET NULL) preserves audit trail
    # after user deletion.
    op.execute(
        """
        CREATE TABLE ai_suggestions (
            id                  uuid        NOT NULL DEFAULT gen_random_uuid(),
            ai_summary_id       uuid        NOT NULL REFERENCES ai_summaries(id) ON DELETE CASCADE,
            project_id          uuid        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            event_id            uuid        NULL,
            suggestion_type     ai_suggestion_type_enum NOT NULL,
            value               text        NOT NULL,
            status              ai_suggestion_status_enum NOT NULL DEFAULT 'pending',
            created_at          timestamptz NOT NULL DEFAULT now(),
            decided_at          timestamptz NULL,
            decided_by_user_id  uuid        NULL REFERENCES users(id) ON DELETE SET NULL,
            PRIMARY KEY (id)
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_ai_suggestions_project_id_status ON ai_suggestions (project_id, status);"
    )
    op.execute(
        "CREATE INDEX ix_ai_suggestions_event_id ON ai_suggestions (event_id);"
    )

    # --- 5. events.ai_score numeric(5,2) NULL ----------------------------------------
    # SCR-04: AI reranking stores clamp result (rule_score ± 15). Matches events.score
    # precision (numeric(5,2)) from migration 013. INSERT-only at scoring time — no
    # UPDATE on compressed chunks per migration 013 precedent. IF NOT EXISTS is a
    # safety guard for idempotent partial re-runs.
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS ai_score numeric(5,2) NULL;")

    # --- 6. projects.ai_* columns ----------------------------------------------------
    # projects is a plain PG table — op.add_column() is safe (no hypertable caveat).
    # Defaults match 17-CONTEXT.md §Decisions: digest_schedule_cron='0 6 * * *',
    # ai_daily_token_cap=100000, ai_digest_enabled=false, ai_rerank_enabled=false.
    op.add_column(
        "projects",
        sa.Column(
            "ai_digest_enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "ai_rerank_enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "ai_daily_token_cap",
            sa.Integer,
            nullable=False,
            server_default="100000",
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "digest_schedule_cron",
            sa.Text,
            nullable=False,
            server_default="0 6 * * *",
        ),
    )


def downgrade() -> None:
    # Reverse order of upgrade().

    # --- 6. Drop projects.ai_* columns -----------------------------------------------
    op.drop_column("projects", "digest_schedule_cron")
    op.drop_column("projects", "ai_daily_token_cap")
    op.drop_column("projects", "ai_rerank_enabled")
    op.drop_column("projects", "ai_digest_enabled")

    # --- 5. Drop events.ai_score -----------------------------------------------------
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS ai_score;")

    # --- 4. Drop ai_suggestions (indexes first) --------------------------------------
    op.execute("DROP INDEX IF EXISTS ix_ai_suggestions_event_id;")
    op.execute("DROP INDEX IF EXISTS ix_ai_suggestions_project_id_status;")
    op.execute("DROP TABLE IF EXISTS ai_suggestions;")

    # --- 3. Drop ai_summaries (indexes first) ----------------------------------------
    op.execute("DROP INDEX IF EXISTS ix_ai_summaries_event_id;")
    op.execute("DROP INDEX IF EXISTS ix_ai_summaries_project_id_created_at;")
    op.execute("DROP TABLE IF EXISTS ai_summaries;")

    # --- 2. Drop ai_providers ---------------------------------------------------------
    op.execute("DROP TABLE IF EXISTS ai_providers;")

    # --- 1. Drop ENUM types ----------------------------------------------------------
    # PG cannot DROP individual ENUM values; we drop the entire type.
    # IF EXISTS is a safety net if a partial upgrade never committed the CREATE TYPE.
    op.execute("DROP TYPE IF EXISTS ai_suggestion_status_enum;")
    op.execute("DROP TYPE IF EXISTS ai_suggestion_type_enum;")
    op.execute("DROP TYPE IF EXISTS ai_summary_type_enum;")
    op.execute("DROP TYPE IF EXISTS ai_provider_type_enum;")
