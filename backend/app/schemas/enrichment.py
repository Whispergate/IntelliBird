"""Pydantic v2 schemas for enrichment endpoints — ENRICH-01, ENRICH-04."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

VerdictType = Literal["clean", "suspicious", "malicious", "unknown"]
ProviderName = Literal["vt", "abuseipdb", "greynoise", "otx", "shodan", "urlhaus"]


class EnrichmentProviderRead(BaseModel):
    """Response schema — never includes raw credentials_enc."""

    id: uuid.UUID
    project_id: uuid.UUID | None
    provider: ProviderName
    enabled: bool
    api_key_masked: str | None  # "••••••••" or None
    daily_request_cap: int | None
    breaker_open_until: datetime | None = None  # populated from Redis at read time
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EnrichmentProviderWrite(BaseModel):
    """Request schema for PUT /api/projects/{id}/enrichment-providers/{provider}."""

    enabled: bool = False
    api_key: str | None = Field(
        default=None, description="Plaintext key — encrypted at router layer"
    )
    daily_request_cap: int | None = None


class IOCEnrichmentRead(BaseModel):
    """Response schema for GET /api/iocs/{id}/enrichments items."""

    id: uuid.UUID
    ioc_id: uuid.UUID
    provider: str
    verdict: VerdictType
    score: float | None
    fetched_at: datetime
    evidence_text: str | None

    model_config = {"from_attributes": True}


class UnifiedVerdictRead(BaseModel):
    """Unified verdict across all providers — worst-case aggregation."""

    verdict: VerdictType
    provider_count: int
    malicious_count: int
    suspicious_count: int


__all__ = [
    "EnrichmentProviderRead",
    "EnrichmentProviderWrite",
    "IOCEnrichmentRead",
    "UnifiedVerdictRead",
    "VerdictType",
    "ProviderName",
]
