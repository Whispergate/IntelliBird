"""Pydantic v2 schemas for Phase 27 sandbox detonation and YARA rule endpoints.

Design notes:
  * SUPPORTED_PROVIDERS is a Literal type used in SandboxConfigCreate to restrict
    provider values to the five supported integrations.
  * compiled_cache is intentionally absent from YaraRuleRead — it is an internal
    binary blob that must never be returned to API clients.
  * SandboxReportRead exposes poll_attempts so the UI can show polling state to operators.
  * SandboxConfigRead deliberately omits api_key_enc (write-only credential field).
"""
from __future__ import annotations

import uuid
import datetime
from typing import Literal

from pydantic import BaseModel, Field

SUPPORTED_PROVIDERS = Literal["cuckoo", "anyrun", "joesandbox", "hybridanalysis", "triage"]


# ---------------------------------------------------------------------------
# SandboxConfig schemas
# ---------------------------------------------------------------------------

class SandboxConfigCreate(BaseModel):
    """Create or upsert a sandbox provider config for a project."""

    provider: SUPPORTED_PROVIDERS
    api_key: str | None = None
    enabled: bool = False
    public_warning_acknowledged: bool = False
    options: dict = Field(default_factory=dict)


class SandboxConfigRead(BaseModel):
    """Read-only view of a sandbox config. api_key_enc is never returned."""

    id: uuid.UUID
    project_id: uuid.UUID
    provider: str
    enabled: bool
    public_warning_acknowledged: bool
    options: dict
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# SandboxReport schemas
# ---------------------------------------------------------------------------

class SandboxReportRead(BaseModel):
    """Full detonation report as returned by GET /sandbox/reports/{id}."""

    id: uuid.UUID
    event_id: uuid.UUID | None = None
    project_id: uuid.UUID
    provider: str
    status: str
    sha256: str
    report_json: dict | None = None
    techniques: list[str] | None = None
    network_iocs: list | None = None
    process_tree: dict | None = None
    score: int | None = None
    verdict: str | None = None
    submitted_at: datetime.datetime
    completed_at: datetime.datetime | None = None
    poll_attempts: int

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# YaraRule schemas
# ---------------------------------------------------------------------------

class YaraRuleCreate(BaseModel):
    """Create a new YARA rule (global or per-project)."""

    name: str = Field(..., min_length=1, max_length=200)
    family: str = Field(default="", max_length=100)
    content: str = Field(..., min_length=1)
    enabled: bool = True
    project_id: uuid.UUID | None = None


class YaraRuleRead(BaseModel):
    """Read-only view of a YARA rule. compiled_cache is NOT included — internal binary."""

    id: uuid.UUID
    name: str
    family: str
    enabled: bool
    project_id: uuid.UUID | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    # NOTE: compiled_cache is intentionally absent — never sent to clients

    model_config = {"from_attributes": True}


class YaraRulePatch(BaseModel):
    """Partial update for a YARA rule (PATCH endpoint)."""

    enabled: bool | None = None
    name: str | None = None
    family: str | None = None
