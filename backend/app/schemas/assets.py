"""Pydantic v2 request + response schemas for /api/projects/{id}/assets.

Phase 12.1 / Project Asset Surface.

Shape invariants (locked by CONTEXT.md + UI-SPEC.md):
- asset_id = sha256(bbot_event_type || canonical_target).hexdigest() — 64 hex chars
- AssetScope enum: in_scope | out_of_scope | unscoped
- AssetExportFormat enum: csv | json
- AssetNotePatch.note: str, max 10_000 chars, empty string allowed
- Seven summary buckets: DOMAINS, IPS, OPEN_PORTS, URLS, TECHNOLOGIES, IDENTITIES, OTHER
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


_ASSET_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_NOTE_MAX_LEN = 10_000


class AssetScope(StrEnum):
    IN_SCOPE = "in_scope"
    OUT_OF_SCOPE = "out_of_scope"
    UNSCOPED = "unscoped"


class AssetExportFormat(StrEnum):
    CSV = "csv"
    JSON = "json"


class StaleFilter(StrEnum):
    SHOW = "show"
    HIDE = "hide"
    ONLY = "only"


SUMMARY_BUCKET_KEYS: tuple[str, ...] = (
    "DOMAINS",
    "IPS",
    "OPEN_PORTS",
    "URLS",
    "TECHNOLOGIES",
    "IDENTITIES",
    "OTHER",
)


class AssetRow(BaseModel):
    """One aggregated asset row — table display + list endpoint items."""

    model_config = ConfigDict(from_attributes=True)

    asset_id: str = Field(
        description="sha256(bbot_event_type + canonical_target) hex digest (64 chars).",
    )
    bbot_event_type: str
    canonical_target: str
    scope: AssetScope
    first_seen: datetime
    last_seen: datetime
    scan_count: int = Field(ge=0)
    modules: list[str]
    stale: bool
    severity_max: str | None = None

    @field_validator("asset_id")
    @classmethod
    def _validate_asset_id(cls, v: str) -> str:
        if not _ASSET_ID_RE.match(v):
            raise ValueError("asset_id must be a 64-char lowercase hex sha256 digest")
        return v


class AssetListResponse(BaseModel):
    items: list[AssetRow]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


class AssetSummaryBucket(BaseModel):
    count: int = Field(ge=0)
    stale_count: int = Field(ge=0)


class AssetSummary(BaseModel):
    """Per-bucket counts for the dashboard summary cards."""

    buckets: dict[str, AssetSummaryBucket]


class AssetFinding(BaseModel):
    """One easm_findings row visible inside the drawer."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scan_id: uuid.UUID
    scan_started_at: datetime
    module: str
    lifecycle_status: str
    severity: str | None = None
    first_seen: datetime
    last_seen: datetime
    raw_bbot: dict[str, Any] | None = None


class AssetPromotedEvent(BaseModel):
    """An events row promoted from this asset (source_type='bbot')."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    stix_type: str
    title: str | None = None
    observed_at: datetime


class AssetNoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    note: str
    updated_by: str
    updated_at: datetime


class AssetNotePatch(BaseModel):
    note: str = Field(max_length=_NOTE_MAX_LEN)


class AssetDetail(AssetRow):
    """Aggregated row + drawer payload."""

    findings: list[AssetFinding]
    promoted_events: list[AssetPromotedEvent]
    note: AssetNoteRead | None = None
