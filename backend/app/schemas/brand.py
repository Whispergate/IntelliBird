"""Brand Protection Pydantic v2 DTOs. Canonical field names locked per
.planning/phases/12-brand-protection/12-CONTEXT.md and 12-UI-SPEC.md.

Phase 12 / BRP-01..BRP-05.

All enum fields use Literal types for compile-time safety + OpenAPI generation —
mirrors the Phase 11 easm.py pattern.

BrandDashboardResponse carries the `has_expiring_dismissals` and
`has_recent_auto_downgrade` banner flags required by the brand dashboard surface
(12-UI-SPEC.md §Data-Loading Contracts).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator



# ---------------------------------------------------------------------------
# Literal enum types — mirror brand_* PG enums from migration 011
# ---------------------------------------------------------------------------
TermType = Literal["keyword", "domain", "product", "person"]
TermMode = Literal["active", "watch_only"]
MatchSource = Literal["fts", "ct_log", "dnstwist"]
MatchSeverity = Literal["low", "medium", "high"]
LifecycleStatus = Literal["new", "confirmed", "dismissed", "watchlist"]


# ---------------------------------------------------------------------------
# Brand-term DTOs
# ---------------------------------------------------------------------------

class BrandTermCreate(BaseModel):
    """POST /api/projects/{id}/brand/terms — create a new watched term.

    `gdpr_consent` MUST be true when `term_type == 'person'` (enforced server-side
    in the router; validator here is lenient to allow partial UI drafts).
    """

    model_config = ConfigDict(extra="forbid")

    term_type: TermType
    value: str = Field(min_length=1, max_length=200)
    gdpr_consent: bool = False


class BrandTermPatch(BaseModel):
    """PATCH /api/projects/{id}/brand/terms/{term_id} — mode flip or archive."""

    model_config = ConfigDict(extra="forbid")

    mode: TermMode | None = None
    archived: bool | None = None


class BrandTermRead(BaseModel):
    """Response shape for a single brand-term row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    term_type: TermType
    value: str
    mode: TermMode
    archived: bool
    high_noise_risk: bool
    created_by: str | None
    created_at: datetime
    # Hydrated by the router via subquery/join when list view requests it;
    # None signals "not joined" rather than zero.
    matches_24h: int | None = None


# ---------------------------------------------------------------------------
# Brand-match DTOs
# ---------------------------------------------------------------------------

class BrandMatchRead(BaseModel):
    """Response shape for a single brand-match row (joined with term for display)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    brand_term_id: UUID
    # Joined from brand_terms for display convenience
    term_value: str | None = None
    term_type: TermType | None = None
    matched_value: str
    match_source: MatchSource
    severity: MatchSeverity
    first_seen: datetime
    last_seen: datetime
    lifecycle_status: LifecycleStatus
    dismiss_until: datetime | None
    match_metadata: dict | None


class BrandMatchPatch(BaseModel):
    """PATCH /api/projects/{id}/brand/matches/{match_id} — lifecycle transition.

    `dismiss_days` is required when `lifecycle_status == 'dismissed'`; validated
    server-side. 1..3650 days (≈10y max).
    `note` is an optional free-text comment (max 500 chars) embedded in the history entry.
    """

    model_config = ConfigDict(extra="forbid")

    lifecycle_status: LifecycleStatus
    dismiss_days: int | None = Field(default=None, ge=1, le=3650)
    note: str | None = Field(default=None, max_length=500)


class BrandSuppressionExtend(BaseModel):
    """POST /api/projects/{id}/brand/matches/{match_id}/extend-suppression.

    `extend_days=None` with `let_resurface=False` means 'Indefinite'
    (sets dismiss_until = NULL while keeping lifecycle_status='dismissed').
    `let_resurface=True` flips lifecycle_status back to 'new' and clears dismiss_until.
    """

    model_config = ConfigDict(extra="forbid")

    extend_days: int | None = Field(default=None, ge=1, le=3650)
    let_resurface: bool = False


# ---------------------------------------------------------------------------
# Match history / details DTOs — Phase 21 / BRAND-02
# ---------------------------------------------------------------------------

class HistoryEntry(BaseModel):
    """A single entry in match_metadata.history[] — written at PATCH time."""

    model_config = ConfigDict(extra="allow")

    acted_at: str
    actor_id: str
    action: str
    prev_status: str | None = None
    new_status: str | None = None
    note: str | None = None
    match_id: str | None = None
    matched_value: str | None = None


class AggregateCounts(BaseModel):
    """Per-status counts across all matches for the same brand_term_id in a project."""

    new: int = 0
    confirmed: int = 0
    dismissed: int = 0
    watchlist: int = 0


class MatchProvenance(BaseModel):
    """Provenance metadata surfaced in the match detail drawer."""

    detector: str           # match_source
    raw_input: str | None   # best available per-detector provenance string
    matched_value: str
    similarity: float | None = None  # always None for current detectors


class MatchDetailsResponse(BaseModel):
    """GET /api/projects/{id}/brand/matches/{match_id}/details response."""

    match_id: UUID
    provenance: MatchProvenance
    aggregate_counts: AggregateCounts
    timeline: list[HistoryEntry]


# ---------------------------------------------------------------------------
# Preview / suppression / dashboard responses
# ---------------------------------------------------------------------------

class BrandPreviewResponse(BaseModel):
    """GET /api/projects/{id}/brand/terms/preview?value=... — noise preview.

    `warning='likely_too_broad'` triggers the 'high_noise_risk' auto-flag on create.
    """

    preview_matches: int
    percent: float
    warning: Literal["likely_too_broad"] | None = None


class BrandSuppressionRow(BaseModel):
    """Row in the suppressed-matches list returned by GET /api/projects/{id}/brand/suppressions."""

    id: UUID
    matched_value: str
    match_source: MatchSource
    dismiss_until: datetime


# ---------------------------------------------------------------------------
# Stoplist DTOs — Phase 21 / BRAND-01
# ---------------------------------------------------------------------------

class BrandStoplistTermCreate(BaseModel):
    """POST /api/projects/{id}/brand/stoplist — add a per-project stoplist term."""

    term: str = Field(..., min_length=1, max_length=200)

    @field_validator("term")
    @classmethod
    def _strip(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("term must not be empty after trim")
        return s


class BrandStoplistTermRead(BaseModel):
    """Response shape for a single brand_stoplist_terms row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    term: str
    created_at: datetime
    created_by_user_id: UUID | None


class BrandDashboardResponse(BaseModel):
    """GET /api/projects/{id}/brand/dashboard — aggregated dashboard payload.

    `has_expiring_dismissals` → show the "X dismissals expiring in 7 days" banner.
    `has_recent_auto_downgrade` → show the "N terms auto-downgraded to watch_only"
    banner; `recent_auto_downgrade_terms` populates the banner copy.
    """

    matches: list[BrandMatchRead]
    has_expiring_dismissals: bool
    has_recent_auto_downgrade: bool
    recent_auto_downgrade_terms: list[str] = []
