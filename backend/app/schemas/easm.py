"""EASM Pydantic v2 DTOs. Canonical field names locked per 11-UI-SPEC.md.

EASM-01..EASM-10.

All enum fields use Literal types for compile-time safety - Wave 2 routers can
validate request bodies and generate OpenAPI schemas without a separate enum registry.
"""
from __future__ import annotations

import uuid
import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Literal enum types - mirrors easm_* PG enums from migration 010
# ---------------------------------------------------------------------------
ScanStatus = Literal["queued", "running", "finished", "failed", "cancelled", "orphaned"]
ScanMode = Literal["passive", "active"]
Severity = Literal["low", "medium", "high", "critical"]
Lifecycle = Literal["new", "confirmed", "dismissed", "watchlist"]
CredentialProvider = Literal["shodan", "github", "bevigil", "chaos", "securitytrails"]


# ---------------------------------------------------------------------------
# Scan DTOs
# ---------------------------------------------------------------------------

class EASMScanCreate(BaseModel):
    """POST /api/projects/{id}/easm/scans - create a new scan."""

    model_config = ConfigDict(extra="forbid")

    scan_mode: ScanMode
    modules: list[str] = Field(min_length=1)


class EASMScanResponse(BaseModel):
    """Response for a single scan row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    status: ScanStatus
    scan_mode: ScanMode
    modules: list[str]
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    stdout_bytes: int
    error: str | None
    launched_by: str
    findings_count: int = 0  # hydrated by router via subquery


# ---------------------------------------------------------------------------
# Finding DTOs
# ---------------------------------------------------------------------------

class EASMFindingResponse(BaseModel):
    """Response for a single finding row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    scan_id: uuid.UUID
    bbot_event_type: str
    canonical_target: str
    severity: Severity | None
    module: str
    raw_bbot: dict
    first_seen: datetime.datetime
    last_seen: datetime.datetime
    lifecycle_status: Lifecycle
    dismiss_until: datetime.datetime | None


class EASMFindingLifecyclePatch(BaseModel):
    """PATCH /api/projects/{id}/easm/findings/{finding_id}/lifecycle."""

    model_config = ConfigDict(extra="forbid")

    lifecycle_status: Lifecycle
    # dismiss_until is server-computed for 'dismissed' (NOW()+30d);
    # clients cannot override the dismiss window.


# ---------------------------------------------------------------------------
# Safelist DTO - GET /api/easm/safelist
# ---------------------------------------------------------------------------

class EASMSafelistResponse(BaseModel):
    """Module safelist returned by GET /api/easm/safelist."""

    modules: list[str]
    bbot_version: str  # e.g. "2.8.4" - pinned in bbot_safelist.py
    requires_credentials: dict[str, str]  # module_name -> provider name (e.g. "shodan_dns": "shodan")


# ---------------------------------------------------------------------------
# Diff DTOs - GET /api/projects/{id}/easm/scans/{scan_id}/diff (EASM-08)
# ---------------------------------------------------------------------------

class EASMDiffEntry(BaseModel):
    """A single finding in a NEW or RESOLVED diff bucket."""

    model_config = ConfigDict(from_attributes=True)

    bbot_event_type: str
    canonical_target: str
    raw_bbot: dict
    module: str
    severity: Severity | None


class EASMDiffChangedEntry(BaseModel):
    """A finding whose raw_bbot changed between two scans."""

    bbot_event_type: str
    canonical_target: str
    previous: dict  # raw_bbot from prior scan
    current: dict   # raw_bbot from this scan
    module: str


class EASMDiffResponse(BaseModel):
    """Response for GET /api/projects/{id}/easm/scans/{scan_id}/diff."""

    this_scan_id: uuid.UUID
    prior_scan_id: uuid.UUID | None
    new: list[EASMDiffEntry]
    changed: list[EASMDiffChangedEntry]
    resolved: list[EASMDiffEntry]


# ---------------------------------------------------------------------------
# Gate flip DTO - POST /api/projects/{id}/easm/gate
# ---------------------------------------------------------------------------

class EASMGateFlipRequest(BaseModel):
    """POST /api/projects/{id}/easm/gate - flip the active-scan authorisation gate.

    scope_acknowledgement_text must exactly match project.name (server-side validated).
    confirm_authorisation must be Literal[True] - the checkbox must be checked.
    """

    model_config = ConfigDict(extra="forbid")

    scope_acknowledgement_text: str  # must exact-match project.name server-side
    confirm_authorisation: Literal[True]  # checkbox - must be True
