"""TIBER report generation ORM models — Phase 18 / TIBER-01..03, AI-08.

Five models for the TIBER report editor and export subsystem:

  TiberReport        — TTIR document row (6-section ECB TIBER-EU / CBEST structure).
                       state: draft → published → archived (app-layer state machine).
                       project_id FK CASCADE is the hard scope boundary for PROD-01.

  TiberActorProfile  — Named threat actor profile row for Threat Actor Profiles section.
                       Denormalised project_id FK CASCADE + tiber_report_id FK CASCADE,
                       mirroring the ai_suggestions dual-FK pattern (migration 014).
                       source_event_ids is a soft JSONB list (events is a hypertable
                       and cannot be a FK target — same pattern as AISummary.event_id).

  TiberScenario      — Scenario chain: actor → CIF/CBS → objective → TTP → procedure.
                       objective_type ENUM {availability, integrity, confidentiality}.
                       actor_id FK (SET NULL) — actor deletion does not cascade-delete
                       the scenario row.
                       ai_draft_metadata JSONB stores AI-drafted badge metadata (AI-08).

  ProjectTiberState  — Per-project TIBER configuration singleton.
                       PK is project_id (one row per project).

  ReportExport       — Binary export store (__tablename__ = 'reports').
                       One row per export action per format.
                       content_bytea: LargeBinary (BYTEA) — 50MB cap enforced by DB CHECK
                       constraint ck_reports_bytea_size (migration 019). NOT included in
                       ExportRead schema (TOAST avoidance per H-5; schema in schemas/tiber.py).
                       report_state_at_export snapshots tiber_reports.state at export time.

All ENUMs use create_type=False — migration 019_tiber.py owns the ENUM lifecycle
(CREATE TYPE in upgrade / DROP TYPE in downgrade). ORM must not attempt to re-create
or drop them independently.

Added by migration 015_tiber (file: 019_tiber.py).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Integer, LargeBinary, Text, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

# ---------------------------------------------------------------------------
# Enum column type definitions — create_type=False because migration owns lifecycle
# ---------------------------------------------------------------------------

_tiber_report_state = PgEnum(
    "draft", "published", "archived",
    name="tiber_report_state_enum",
    create_type=False,
)

_report_format = PgEnum(
    "markdown", "pdf", "stix",
    name="report_format_enum",
    create_type=False,
)

_scenario_objective = PgEnum(
    "availability", "integrity", "confidentiality",
    name="scenario_objective_enum",
    create_type=False,
)


class TiberReport(Base):
    """Core TTIR document row.

    Phase 18 / TIBER-01. Stores all 6-section TIBER-EU / CBEST fields.
    state machine: draft (default) → published → archived.
    project_id FK CASCADE is the hard PROD-01 scope boundary.

    Relationships (cascade="all, delete-orphan"):
      actors   → TiberActorProfile rows for this report
      scenarios → TiberScenario rows for this report
      exports  → ReportExport rows for this report
    """

    __tablename__ = "tiber_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    cbest_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    state: Mapped[str] = mapped_column(
        _tiber_report_state,
        nullable=False,
        server_default="draft",
    )
    # Scope of Intelligence Research — engagement window dates
    engagement_window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    engagement_window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Scope of Intelligence Research — asset lists
    in_scope_assets: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    out_of_scope_assets: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # Actionable Intelligence Assessment
    aia_summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    aia_recommendations: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # Threat Landscape
    tl_top_events: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    tl_analyst_narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    tl_top_events_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("20")
    )
    # Scenario X — free-form analyst narrative
    scenario_x_narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    # FK (SET NULL) — preserves audit trail after user deletion
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    actors: Mapped[list["TiberActorProfile"]] = relationship(
        "TiberActorProfile",
        back_populates="report",
        cascade="all, delete-orphan",
    )
    scenarios: Mapped[list["TiberScenario"]] = relationship(
        "TiberScenario",
        back_populates="report",
        cascade="all, delete-orphan",
    )
    exports: Mapped[list["ReportExport"]] = relationship(
        "ReportExport",
        back_populates="report",
        cascade="all, delete-orphan",
    )


class TiberActorProfile(Base):
    """Named threat actor profile row.

    Phase 18 / TIBER-01. Belongs to one TiberReport; carries a denormalised
    project_id FK CASCADE for direct project-scope queries without joining
    through tiber_reports (PROD-01 / H-4 mitigation; mirrors ai_suggestions
    dual-FK pattern from migration 014).

    source_event_ids is a soft JSONB list of event UUIDs — no FK constraint
    because events is a TimescaleDB hypertable and CANNOT be a FK target
    (same pattern as AISummary.event_id, AISuggestion.event_id).
    """

    __tablename__ = "tiber_actor_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tiber_report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tiber_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    motivation: Mapped[str | None] = mapped_column(Text, nullable=True)
    capability_assessment: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevance_to_target: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Soft list of event UUIDs — no FK to hypertable
    source_event_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    # Relationship back to TiberReport
    report: Mapped["TiberReport"] = relationship(
        "TiberReport", back_populates="actors"
    )


class TiberScenario(Base):
    """Threat scenario chain row.

    Phase 18 / TIBER-02. Represents one scenario in the longlist:
      actor (FK) → CIF/CBS label → objective type → ATT&CK technique → procedure prose.

    actor_id FK (SET NULL): actor profile deletion does not cascade-delete
    the scenario; scenario survives with actor_id=NULL.

    ai_draft_metadata JSONB: stores metadata for the AI-drafted badge (AI-08):
      {"ai_drafted": true, "edited_by": "<user_id>", "edited_at": "<iso8601>"}
    Included in BYTEA export header for audit trail (CONTEXT.md §AI-08).

    sort_order integer: UI drag-reorder position within the longlist.
    selected_for_inclusion boolean: only true rows count toward the 3-scenario gate.
    """

    __tablename__ = "tiber_scenarios"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tiber_report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tiber_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    # FK (SET NULL) — actor deletion orphans the scenario rather than deleting it
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tiber_actor_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    cif_or_cbs_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    objective_type: Mapped[str | None] = mapped_column(
        _scenario_objective, nullable=True
    )
    attack_technique_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    procedure_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_for_inclusion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    ai_draft_narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_draft_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    # Relationship back to TiberReport
    report: Mapped["TiberReport"] = relationship(
        "TiberReport", back_populates="scenarios"
    )


class ProjectTiberState(Base):
    """Per-project TIBER configuration singleton.

    Phase 18 / TIBER-01. PK is project_id (one row per project).
    default_top_events_n — project-level default for Threat Landscape auto-populate N.
    Individual reports can override via tiber_reports.tl_top_events_count.
    tiber_phase — free-text engagement phase label (e.g. 'Preparation', 'Testing');
    NULL until set by operator.
    """

    __tablename__ = "project_tiber_state"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    default_top_events_n: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("20")
    )
    tiber_phase: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class ReportExport(Base):
    """Binary export store row (__tablename__ = 'reports').

    Phase 18 / TIBER-03. One row per export action per format.
    version_number is monotonic per (tiber_report_id, format) — application layer
    assigns next version = MAX(version_number) + 1 for the (report_id, format) pair
    before INSERT.

    content_bytea: LargeBinary (BYTEA) — the actual export bytes.
    50MB hard cap enforced by DB CHECK constraint ck_reports_bytea_size (migration 019).
    NOT included in ExportRead schema — TOAST avoidance per H-5: listing the history
    sidebar must NOT load BYTEA content; only the metadata row is read for the list.
    content_bytea is only fetched on explicit download requests.

    report_state_at_export: snapshot of tiber_reports.state at export time.
    Provides an immutable audit record of the exact report state when bytes were
    generated, even after subsequent state transitions (draft → published, etc.).

    generated_by_user_id FK (SET NULL): preserves audit trail after user deletion.
    """

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tiber_report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tiber_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    format: Mapped[str] = mapped_column(_report_format, nullable=False)
    version_number: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    # BYTEA column — 50MB cap enforced by DB CHECK ck_reports_bytea_size.
    # NOT read by ExportRead schema (TOAST avoidance / H-5).
    content_bytea: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    # FK (SET NULL) — preserves audit trail after user deletion
    generated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    report_state_at_export: Mapped[str] = mapped_column(
        _tiber_report_state, nullable=False
    )

    # Relationship back to TiberReport
    report: Mapped["TiberReport"] = relationship(
        "TiberReport", back_populates="exports"
    )
