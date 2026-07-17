"""TIBER report generation schema — TIBER-01..03, AI-08.

Revision ID: 015_tiber
Revises: 014_ai
Create Date: 2026-04-25

(Filename 019_tiber.py reflects insertion order; revision id is "015_tiber"
because models/tests reference that id. Follows linear chain after 014_ai.)

TIBER-01, TIBER-02, TIBER-03, AI-08.

Schema foundation for the TIBER report editor + exporter + history:

  tiber_reports table
    TIBER-01: One TTIR (Targeted Threat Intelligence Report) per engagement.
    Stores the 6-section TIBER-EU / CBEST structure. project_id FK CASCADE
    is the hard project scope boundary (PROD-01 / H-4 pattern — every
    project-scoped table carries project_id FK with ON DELETE CASCADE so the
    scope chokepoint in build_scope_predicate is always reachable via simple
    predicate). state: draft → published → archived (state machine enforced at
    app layer; schema records the current state).

  tiber_actor_profiles table
    TIBER-01: Named threat actor profile rows for Threat Actor Profiles section.
    Denormalised project_id FK CASCADE alongside tiber_report_id FK CASCADE
    mirrors the ai_suggestions multi-FK pattern from migration 014 — direct
    project scope column avoids join through tiber_reports for scope isolation.

  tiber_scenarios table
    TIBER-02: Scenario chains (actor → CIF/CBS → objective → TTP → procedure).
    objective_type ENUM {availability, integrity, confidentiality} per ECB
    TIBER-EU TTIR Jan 2025 §Threat Scenarios. actor_id FK (SET NULL) allows
    actor deletion without cascade-deleting the scenario row.

  project_tiber_state table
    TIBER-01: Per-project TIBER configuration. PK is project_id (one row per
    project). default_top_events_n controls Threat Landscape auto-populate.

  reports table
    TIBER-03: Binary export store. One BYTEA row per export action per format.
    version_number is monotonic per (tiber_report_id, format). 50MB hard cap
    enforced by DB CHECK constraint ck_reports_bytea_size (octet_length ≤ 52428800).
    report_state_at_export snapshots the tiber_reports.state at export time for
    audit trail — provides exact state that was in effect when the bytes were
    generated, even after later state transitions.

  Three ENUMs (idempotent DO $$ EXCEPTION WHEN duplicate_object guard):
    tiber_report_state_enum: draft, published, archived
    report_format_enum:      markdown, pdf, stix
    scenario_objective_enum: availability, integrity, confidentiality

ADD COLUMN safety:
  No hypertable columns modified in this migration — all DDL is CREATE TABLE
  and CREATE TYPE. No split-statement requirement applies here.

Cascade count: ≥6 ON DELETE CASCADE FKs across 5 tables (one per project_id FK
  on tiber_reports + tiber_actor_profiles + tiber_scenarios + reports, plus two
  tiber_report_id FKs on tiber_actor_profiles → tiber_reports and
  tiber_scenarios → tiber_reports and reports → tiber_reports).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "015_tiber"
down_revision: Union[str, None] = "014_ai"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. ENUM types (idempotent DO $$ guard) -------------------------------------
    # Pattern from migrations 003, 006, 009, 014, 016: EXCEPTION WHEN duplicate_object
    # allows safe re-run after partial migration failure without raising errors.

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE tiber_report_state_enum AS ENUM ('draft', 'published', 'archived');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE report_format_enum AS ENUM ('markdown', 'pdf', 'stix');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE scenario_objective_enum AS ENUM (
                'availability', 'integrity', 'confidentiality'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    # --- 2. tiber_reports table -------------------------------------------------------
    # TIBER-01: Core TTIR document row. Stores all 6-section fields.
    # cbest_mode boolean — when true, frontend/exporter replaces "CIF" with
    # "Critical Business Service" in labels and export output.
    # in_scope_assets, out_of_scope_assets, aia_recommendations, tl_top_events are
    # JSONB arrays (default '[]') — analyst-editable lists, auto-populated from
    # project scope data and event feed respectively.
    # created_by_user_id FK (SET NULL) — preserves audit trail after user deletion.
    op.execute(
        """
        CREATE TABLE tiber_reports (
            id                      uuid                    NOT NULL DEFAULT gen_random_uuid(),
            project_id              uuid                    NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            title                   text                    NOT NULL,
            cbest_mode              boolean                 NOT NULL DEFAULT false,
            state                   tiber_report_state_enum NOT NULL DEFAULT 'draft',
            engagement_window_start date                    NULL,
            engagement_window_end   date                    NULL,
            in_scope_assets         jsonb                   NOT NULL DEFAULT '[]'::jsonb,
            out_of_scope_assets     jsonb                   NOT NULL DEFAULT '[]'::jsonb,
            aia_summary_text        text                    NULL,
            aia_recommendations     jsonb                   NOT NULL DEFAULT '[]'::jsonb,
            tl_top_events           jsonb                   NOT NULL DEFAULT '[]'::jsonb,
            tl_analyst_narrative    text                    NULL,
            tl_top_events_count     int                     NOT NULL DEFAULT 20,
            scenario_x_narrative    text                    NULL,
            created_at              timestamptz             NOT NULL DEFAULT now(),
            updated_at              timestamptz             NOT NULL DEFAULT now(),
            created_by_user_id      uuid                    NULL REFERENCES users(id) ON DELETE SET NULL,
            PRIMARY KEY (id)
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_tiber_reports_project_id_state ON tiber_reports (project_id, state);"
    )

    # --- 3. tiber_actor_profiles table -----------------------------------------------
    # TIBER-01: Named threat actor profiles. Denormalised project_id FK CASCADE
    # mirrors ai_suggestions dual-FK pattern (migration 014) — direct scope column
    # avoids join through tiber_reports for project-scope isolation (PROD-01 / H-4).
    # source_event_ids JSONB — list of event UUIDs (soft refs; events is a hypertable
    # and cannot be FK targets — same pattern as AISummary.event_id in migration 014).
    op.execute(
        """
        CREATE TABLE tiber_actor_profiles (
            id                      uuid        NOT NULL DEFAULT gen_random_uuid(),
            tiber_report_id         uuid        NOT NULL REFERENCES tiber_reports(id) ON DELETE CASCADE,
            project_id              uuid        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name                    text        NOT NULL,
            motivation              text        NULL,
            capability_assessment   text        NULL,
            relevance_to_target     text        NULL,
            source_event_ids        jsonb       NOT NULL DEFAULT '[]'::jsonb,
            created_at              timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (id)
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_tiber_actor_profiles_report_id ON tiber_actor_profiles (tiber_report_id);"
    )

    # --- 4. tiber_scenarios table -----------------------------------------------------
    # TIBER-02: Scenario chain rows. Each row is one threat scenario:
    #   actor → CIF/CBS label → objective type → ATT&CK technique → procedure prose.
    # actor_id FK (SET NULL) — actor profile deletion does not cascade-delete the
    # scenario; scenario survives with actor_id=NULL (orphaned actor reference).
    # ai_draft_metadata JSONB — stores 'ai_drafted', 'edited_by', 'edited_at' fields
    # for the AI-drafted badge (AI-08; CONTEXT.md §AI-08 scenario narrative).
    # sort_order integer — for UI drag-reorder within the longlist.
    op.execute(
        """
        CREATE TABLE tiber_scenarios (
            id                      uuid                    NOT NULL DEFAULT gen_random_uuid(),
            tiber_report_id         uuid                    NOT NULL REFERENCES tiber_reports(id) ON DELETE CASCADE,
            project_id              uuid                    NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            actor_id                uuid                    NULL REFERENCES tiber_actor_profiles(id) ON DELETE SET NULL,
            cif_or_cbs_label        text                    NULL,
            objective_type          scenario_objective_enum NULL,
            attack_technique_id     text                    NULL,
            procedure_text          text                    NULL,
            selected_for_inclusion  boolean                 NOT NULL DEFAULT false,
            ai_draft_narrative      text                    NULL,
            ai_draft_metadata       jsonb                   NULL,
            sort_order              int                     NOT NULL DEFAULT 0,
            created_at              timestamptz             NOT NULL DEFAULT now(),
            updated_at              timestamptz             NOT NULL DEFAULT now(),
            PRIMARY KEY (id)
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_tiber_scenarios_report_selected ON tiber_scenarios (tiber_report_id, selected_for_inclusion);"
    )

    # --- 5. project_tiber_state table ------------------------------------------------
    # TIBER-01: Per-project TIBER configuration singleton.
    # PK is project_id (one row per project — no separate uuid PK).
    # default_top_events_n — Threat Landscape auto-populate N; per-report override
    # stored on tiber_reports.tl_top_events_count (this is the project default).
    # tiber_phase — free-text project engagement phase label (e.g. 'Preparation',
    # 'Testing', 'Closure'); NULL until operator sets it.
    op.execute(
        """
        CREATE TABLE project_tiber_state (
            project_id          uuid        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            default_top_events_n int        NOT NULL DEFAULT 20,
            tiber_phase         text        NULL,
            created_at          timestamptz NOT NULL DEFAULT now(),
            updated_at          timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (project_id)
        );
        """
    )

    # --- 6. reports table ------------------------------------------------------------
    # TIBER-03: Binary export store. One row per export action per format.
    # content_bytea — actual export bytes (Markdown text, PDF binary, STIX JSON).
    # 50MB hard cap enforced by CHECK constraint ck_reports_bytea_size.
    # version_number — monotonic per (tiber_report_id, format); application layer
    # assigns next version = MAX(version_number) + 1 for this (report_id, format)
    # pair before INSERT.
    # report_state_at_export — snapshot of tiber_reports.state at export time for
    # immutable audit trail (CONTEXT.md §Versioning / H-5 TOAST avoidance note).
    # generated_by_user_id FK (SET NULL) — preserves audit trail after user deletion.
    op.execute(
        """
        CREATE TABLE reports (
            id                      uuid                    NOT NULL DEFAULT gen_random_uuid(),
            tiber_report_id         uuid                    NOT NULL REFERENCES tiber_reports(id) ON DELETE CASCADE,
            project_id              uuid                    NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            format                  report_format_enum      NOT NULL,
            version_number          int                     NOT NULL DEFAULT 1,
            content_bytea           bytea                   NOT NULL,
            filename                text                    NOT NULL,
            generated_at            timestamptz             NOT NULL DEFAULT now(),
            generated_by_user_id    uuid                    NULL REFERENCES users(id) ON DELETE SET NULL,
            report_state_at_export  tiber_report_state_enum NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT ck_reports_bytea_size CHECK (octet_length(content_bytea) <= 52428800)
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_reports_tiber_report_id_format ON reports (tiber_report_id, format, version_number DESC);"
    )


def downgrade() -> None:
    # Reverse in strict opposite order of upgrade().
    # Tables are dropped in reverse FK dependency order:
    # reports → project_tiber_state → tiber_scenarios → tiber_actor_profiles → tiber_reports
    # ENUMs are dropped after all tables that reference them.

    # --- 6. Drop reports (index first) -----------------------------------------------
    op.execute("DROP INDEX IF EXISTS ix_reports_tiber_report_id_format;")
    op.execute("DROP TABLE IF EXISTS reports;")

    # --- 5. Drop project_tiber_state -------------------------------------------------
    op.execute("DROP TABLE IF EXISTS project_tiber_state;")

    # --- 4. Drop tiber_scenarios (index first) ----------------------------------------
    op.execute("DROP INDEX IF EXISTS ix_tiber_scenarios_report_selected;")
    op.execute("DROP TABLE IF EXISTS tiber_scenarios;")

    # --- 3. Drop tiber_actor_profiles (index first) ----------------------------------
    op.execute("DROP INDEX IF EXISTS ix_tiber_actor_profiles_report_id;")
    op.execute("DROP TABLE IF EXISTS tiber_actor_profiles;")

    # --- 2. Drop tiber_reports (index first) -----------------------------------------
    op.execute("DROP INDEX IF EXISTS ix_tiber_reports_project_id_state;")
    op.execute("DROP TABLE IF EXISTS tiber_reports;")

    # --- 1. Drop ENUM types ----------------------------------------------------------
    # PG cannot DROP individual ENUM values; we drop the entire type.
    # IF EXISTS is a safety net if a partial upgrade never committed the CREATE TYPE.
    op.execute("DROP TYPE IF EXISTS scenario_objective_enum;")
    op.execute("DROP TYPE IF EXISTS report_format_enum;")
    op.execute("DROP TYPE IF EXISTS tiber_report_state_enum;")
