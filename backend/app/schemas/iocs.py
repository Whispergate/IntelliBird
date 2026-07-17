"""Pydantic v2 schemas for IOC API surface — IOC-01..08.

Exports:
  * IOCRead — GET /api/iocs response row
  * IOCCreate — POST /api/iocs body (server applies type-aware ttl_days /
    confidence defaults if not supplied)
  * IOCPatch — PATCH /api/iocs/{id} (Lead+ on row's project; confidence + ttl_days only)
  * IOCImportRow — per-row payload from csv_parser / json_parser / stix_parser;
    accepts optional `project_id` and `source` per 22-CONTEXT.md CSV columns spec
    (admin uploads may use project_id=None for global rows)
  * IOCBulkImportDryRun — preview counts returned by ?dry_run=true
  * IOCBulkImportEnqueued — {job_id, rows_accepted} returned by real run
  * IOCType / IOCStatus / IOCSource — Literal aliases for OpenAPI clarity
  * IOC_TYPE_ENUM_VALUES / IOC_TTL_DEFAULTS — re-exported for convenience
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.iocs import IOC_TTL_DEFAULTS, IOC_TYPE_ENUM_VALUES

IOCType = Literal[
    "ip", "ipv6", "domain", "url",
    "sha256", "sha1", "md5",
    "email", "btc", "eth", "mutex", "registry_key", "filename",
]
IOCStatus = Literal["active", "expired", "whitelisted"]
IOCSource = Literal["manual", "csv", "json", "stix", "event", "backfill"]


class IOCRead(BaseModel):
    """GET /api/iocs row shape. ORM-mode via from_attributes."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID | None
    type: IOCType
    value: str
    normalized_value: str
    status: IOCStatus
    confidence: Decimal
    ttl_days: int
    source: IOCSource
    first_seen: datetime
    last_seen: datetime
    created_at: datetime
    updated_at: datetime
    created_by: str | None


class IOCCreate(BaseModel):
    """POST /api/iocs body. Server-side defaults:
      * confidence → 0.7 if None
      * ttl_days   → IOC_TTL_DEFAULTS[type] if None
      * source     → 'manual'
    """

    type: IOCType
    value: str = Field(min_length=1, max_length=2048)
    confidence: Decimal | None = None
    ttl_days: int | None = None
    source: IOCSource = "manual"
    project_id: uuid.UUID | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None


class IOCPatch(BaseModel):
    """PATCH /api/iocs/{id} — partial update.

    Lead+ on row's project required. Whitelist toggles + lifecycle status
    transitions go through dedicated endpoints (POST .../whitelist) to keep
    audit trails distinct.
    """

    confidence: Decimal | None = None
    ttl_days: int | None = None


class IOCImportRow(BaseModel):
    """Per-row import payload — produced by csv_parser, json_parser, stix_parser.

    `project_id` and `source` accepted per 22-CONTEXT.md CSV columns spec.

    Authorisation rules (enforced server-side at the route level):
      * Non-admin uploads — `project_id` MUST equal the route project_id
        (mismatch → 422). NULL allowed only for Admins.
      * Admin uploads — `project_id` may be None or the literal string 'global'
        (parser converts 'global' → None) for global rows.
    """

    type: IOCType
    value: str
    confidence: Decimal | None = None
    ttl_days: int | None = None
    # Default applied server-side based on import format (csv/json/stix).
    source: IOCSource | None = None
    # Default = route project; None = global (Admin-only).
    project_id: uuid.UUID | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    # Diagnostics — populated by parsers for error reporting in dry-run.
    line: int | None = None
    error: str | None = None


class IOCBulkImportDryRun(BaseModel):
    """Counts returned by POST /api/iocs/bulk-import?dry_run=true."""

    would_insert: int
    would_update: int
    would_skip: int
    unmapped_sdo_count: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)


class IOCBulkImportEnqueued(BaseModel):
    """Real-run response — UI polls Redis for job progress."""

    job_id: str
    rows_accepted: int


__all__ = [
    "IOCRead",
    "IOCCreate",
    "IOCPatch",
    "IOCImportRow",
    "IOCBulkImportDryRun",
    "IOCBulkImportEnqueued",
    "IOCType",
    "IOCStatus",
    "IOCSource",
    "IOC_TYPE_ENUM_VALUES",
    "IOC_TTL_DEFAULTS",
]
