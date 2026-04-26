"""Pydantic v2 schemas for TIBER report editor API — Phase 18 / TIBER-01..03, AI-08.

Exports:
  ReportState          — str Enum: draft | published | archived
  ReportFormat         — str Enum: markdown | pdf | stix
  ObjectiveType        — str Enum: availability | integrity | confidentiality

  TiberReportCreate    — POST /api/projects/{id}/tiber body
  TiberReportPatch     — PATCH /api/projects/{id}/tiber/{report_id} body
                         State transitions are NOT in patch shape — use POST /publish
                         and POST /archive endpoints. extra="forbid" blocks state in patch.
  TiberReportRead      — GET /api/projects/{id}/tiber/{report_id} response

  ActorProfileCreate   — POST /api/projects/{id}/tiber/{report_id}/actors body
  ActorProfileRead     — actor row response

  ScenarioPatch        — PATCH /api/projects/{id}/tiber/{report_id}/scenarios/{id} body
                         attack_technique_id validates ATT&CK ID format T[0-9]{4}(.[0-9]{3})?
  ScenarioRead         — scenario row response (includes ai_draft_metadata)

  ExportCreate         — POST /api/projects/{id}/tiber/{report_id}/exports body
  ExportRead           — export metadata row response (NO content_bytea — H-5 TOAST avoidance)

  RefreshDiffRow       — one field diff row in refresh modal
  RefreshDiffResponse  — full diff response for a named section
  RefreshDiffApply     — PATCH body: list of accepted field paths

  CompletenessReport   — response for completeness gate endpoint
  ScenarioGateReport   — response for scenario count gate endpoint
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Enum types
# ---------------------------------------------------------------------------


class ReportState(str, Enum):
    """TIBER report state machine values."""

    draft = "draft"
    published = "published"
    archived = "archived"


class ReportFormat(str, Enum):
    """Supported export formats."""

    markdown = "markdown"
    pdf = "pdf"
    stix = "stix"


class ObjectiveType(str, Enum):
    """ECB TIBER-EU Threat Scenarios — scenario objective type."""

    availability = "availability"
    integrity = "integrity"
    confidentiality = "confidentiality"


# ---------------------------------------------------------------------------
# TiberReport schemas
# ---------------------------------------------------------------------------


class TiberReportCreate(BaseModel):
    """POST /api/projects/{id}/tiber — create a new TIBER report draft.

    title: 1–300 characters, non-empty.
    cbest_mode: when True, "CIF" is relabelled "Critical Business Service" in
    exporter output and UI labels (surface-only — same DB columns).
    """

    title: str = Field(min_length=1, max_length=300)
    cbest_mode: bool = False


class TiberReportPatch(BaseModel):
    """PATCH /api/projects/{id}/tiber/{report_id} — partial update of report fields.

    State transitions are NOT part of this schema. State changes go through
    dedicated endpoints:
      POST /tiber/{report_id}/publish   → draft → published
      POST /tiber/{report_id}/archive   → published → archived  (Admin only)
      POST /tiber/{report_id}/clone     → creates new draft from published

    extra="forbid" ensures any attempt to pass `state` in the PATCH body
    raises a ValidationError (422) — the router never sees a state change
    through this path. This is the primary enforcement mechanism for the
    state machine at the schema layer.

    tl_top_events_count: 1–500 (allows high-event-volume projects; 500 is a
    sensible upper bound to prevent accidental 10k-row auto-populate).
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=300)
    cbest_mode: bool | None = None
    engagement_window_start: date | None = None
    engagement_window_end: date | None = None
    in_scope_assets: list[str] | None = None
    out_of_scope_assets: list[str] | None = None
    aia_summary_text: str | None = None
    aia_recommendations: list[str] | None = None
    tl_analyst_narrative: str | None = None
    tl_top_events_count: int | None = Field(default=None, ge=1, le=500)
    scenario_x_narrative: str | None = None


class TiberReportRead(BaseModel):
    """GET /api/projects/{id}/tiber/{report_id} — full report metadata response.

    from_attributes=True enables construction from TiberReport ORM rows.
    tl_top_events is a list of event dicts (JSONB); populated by auto-populate
    or refresh diff apply. Returned as-is (not sub-typed here — shape evolved
    by exporter).

    NOTE: actor_profiles and scenarios lists are intentionally omitted from this
    schema. Actors and scenarios are fetched by dedicated list endpoints to avoid
    TOAST loading on every report metadata read (H-5).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    cbest_mode: bool
    state: ReportState
    engagement_window_start: date | None
    engagement_window_end: date | None
    in_scope_assets: list[str]
    out_of_scope_assets: list[str]
    aia_summary_text: str | None
    aia_recommendations: list[str]
    tl_top_events: list[dict]
    tl_analyst_narrative: str | None
    tl_top_events_count: int
    scenario_x_narrative: str | None
    created_at: datetime
    updated_at: datetime
    created_by_user_id: uuid.UUID | None


# ---------------------------------------------------------------------------
# TiberActorProfile schemas
# ---------------------------------------------------------------------------


class ActorProfileCreate(BaseModel):
    """POST /api/projects/{id}/tiber/{report_id}/actors — create an actor profile.

    name: 1+ character, non-empty.
    motivation, capability_assessment, relevance_to_target: optional text fields.
    Can be filled progressively (auto-populate fills them; analyst edits).
    """

    name: str = Field(min_length=1)
    motivation: str | None = None
    capability_assessment: str | None = None
    relevance_to_target: str | None = None


class ActorProfileRead(BaseModel):
    """Actor profile row response.

    source_event_ids: list of event UUID strings (soft refs — no FK to hypertable).
    from_attributes=True enables construction from TiberActorProfile ORM rows.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tiber_report_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    motivation: str | None
    capability_assessment: str | None
    relevance_to_target: str | None
    source_event_ids: list[str]
    created_at: datetime


# ---------------------------------------------------------------------------
# TiberScenario schemas
# ---------------------------------------------------------------------------


class ScenarioPatch(BaseModel):
    """PATCH /api/projects/{id}/tiber/{report_id}/scenarios/{id}.

    All fields are optional — partial updates only. extra="forbid" prevents
    unknown fields being silently accepted.

    attack_technique_id: validated against ATT&CK ID format T[0-9]{4}(.[0-9]{3})?
    Examples: T1566 (valid), T1566.001 (valid), T1566.1 (invalid — must be 3 digits),
    CVE-2021-1234 (invalid). NULL / None is allowed (clears the field).

    selected_for_inclusion: the scenario counts toward the 3-scenario gate when True
    and all required fields (actor_id, cif_or_cbs_label, objective_type,
    attack_technique_id, procedure_text) are non-null. Gate checked by validators.py,
    not this schema.
    """

    model_config = ConfigDict(extra="forbid")

    actor_id: uuid.UUID | None = None
    cif_or_cbs_label: str | None = None
    objective_type: ObjectiveType | None = None
    attack_technique_id: str | None = Field(
        default=None,
        pattern=r"^T\d{4}(\.\d{3})?$",
    )
    procedure_text: str | None = None
    selected_for_inclusion: bool | None = None
    sort_order: int | None = None
    ai_draft_narrative: str | None = None


class ScenarioRead(BaseModel):
    """Scenario row response.

    ai_draft_metadata: dict carrying AI-drafted badge metadata (AI-08):
      {"ai_drafted": true, "edited_by": "<user_id>", "edited_at": "<iso8601>"}
    from_attributes=True enables construction from TiberScenario ORM rows.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tiber_report_id: uuid.UUID
    project_id: uuid.UUID
    actor_id: uuid.UUID | None
    cif_or_cbs_label: str | None
    objective_type: ObjectiveType | None
    attack_technique_id: str | None
    procedure_text: str | None
    selected_for_inclusion: bool
    ai_draft_narrative: str | None
    ai_draft_metadata: dict | None
    sort_order: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Export schemas
# ---------------------------------------------------------------------------


class ExportCreate(BaseModel):
    """POST /api/projects/{id}/tiber/{report_id}/exports — trigger export.

    format: one of markdown | pdf | stix.
    The export worker assigns version_number = MAX(version_number) + 1 for
    the (tiber_report_id, format) pair before INSERT (monotonic per format).
    """

    format: ReportFormat


class ExportRead(BaseModel):
    """Export metadata row response for history sidebar.

    IMPORTANT: content_bytea is deliberately EXCLUDED from this schema.
    Loading BYTEA content for every row in the history list would force
    PostgreSQL to dereference the TOAST pointer for each row, causing
    excessive I/O on reports with large blobs (H-5 mitigation).

    content_bytea is only loaded on explicit download requests:
      GET /api/projects/{id}/tiber/{report_id}/exports/{export_id}/download

    from_attributes=True enables construction from ReportExport ORM rows.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tiber_report_id: uuid.UUID
    project_id: uuid.UUID
    format: ReportFormat
    version_number: int
    filename: str
    generated_at: datetime
    generated_by_user_id: uuid.UUID | None
    report_state_at_export: ReportState


# ---------------------------------------------------------------------------
# Refresh diff schemas (auto-populate diff modal)
# ---------------------------------------------------------------------------


class RefreshDiffRow(BaseModel):
    """One field-level diff row in the refresh modal.

    field_path: dot-notation path to the field being updated
      e.g. "tl_top_events[3].title" or "aia_summary_text"
    current_value: the field's current value in the DB (shown in left column)
    new_value: the freshly auto-populated value (shown in right column)
    """

    field_path: str
    current_value: Any | None = None
    new_value: Any


class RefreshDiffResponse(BaseModel):
    """Full diff response for one named section's refresh.

    section: one of the four auto-populated section keys.
    rows: list of field-level diff rows for the analyst to review.
    """

    section: Literal[
        "actionable_intelligence",
        "threat_landscape",
        "actor_profiles",
        "scenarios",
    ]
    rows: list[RefreshDiffRow]


class RefreshDiffApply(BaseModel):
    """PATCH body for accepting selected diff rows.

    accepted_field_paths: list of field_path strings from RefreshDiffRow that
    the analyst has accepted. Only these paths will be written to the DB.
    Unaccepted paths are discarded — no silent overwrite of analyst edits.
    """

    accepted_field_paths: list[str]


# ---------------------------------------------------------------------------
# Completeness + scenario gate schemas
# ---------------------------------------------------------------------------


class CompletenessReport(BaseModel):
    """Response for GET /api/projects/{id}/tiber/{report_id}/completeness.

    sections: mapping of section key → list of missing required field names.
    An empty list means the section is complete.
    Export is blocked until all lists are empty.

    Section keys match TIBER-EU 6-section structure:
      scope_of_intelligence_research
      actionable_intelligence_assessment
      threat_landscape
      threat_actor_profiles
      threat_scenarios
      scenario_x
    """

    sections: dict[str, list[str]]


class ScenarioGateReport(BaseModel):
    """Response for GET /api/projects/{id}/tiber/{report_id}/scenario-gate.

    selected_count: scenarios with selected_for_inclusion=True AND all required
    fields filled (actor_id, cif_or_cbs_label, objective_type, attack_technique_id,
    procedure_text all non-null). Must be ≥3 to pass export gate.

    longlist_count: total scenarios for this report (max 6).

    missing_per_scenario: mapping of scenario_id → list of missing required field
    names for each incomplete scenario in the longlist. Used by frontend to show
    per-scenario inline validation badges.
    """

    selected_count: int
    longlist_count: int
    missing_per_scenario: dict[uuid.UUID, list[str]]
