"""Pydantic v2 schemas for TAXII 2.1 outbound server — TAXII-01..05.

Naming follows OASIS TAXII 2.1 spec §4-§6 resource names exactly.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# TAXII 2.1 discovery + API root resources (spec §4)
# ---------------------------------------------------------------------------

class DiscoveryResource(BaseModel):
    """OASIS TAXII 2.1 §4.1 — Discovery Resource."""
    model_config = ConfigDict(populate_by_name=True)

    title: str
    description: str | None = None
    contact: str | None = None
    default: str | None = None
    api_roots: list[str] = Field(default_factory=list)


class ApiRootResource(BaseModel):
    """OASIS TAXII 2.1 §5.1 — API Root Resource."""
    title: str
    description: str | None = None
    versions: list[str] = Field(default_factory=lambda: ["application/taxii+json;version=2.1"])
    max_content_length: int = 10_485_760  # 10 MB


# ---------------------------------------------------------------------------
# TAXII 2.1 collection resource (spec §5.2)
# ---------------------------------------------------------------------------

class CollectionResource(BaseModel):
    """OASIS TAXII 2.1 §5.2 — Collection Resource."""
    model_config = ConfigDict(populate_by_name=True)

    id: str                   # UUID string matching project UUID
    title: str
    description: str | None = None
    can_read: bool = True
    can_write: bool = False   # outbound server is read-only
    media_types: list[str] = Field(
        default_factory=lambda: ["application/stix+json;version=2.1"]
    )


class CollectionsResource(BaseModel):
    """OASIS TAXII 2.1 §5.2 — Collections wrapper."""
    collections: list[CollectionResource] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# TAXII 2.1 objects endpoint envelope (spec §5.4)
# ---------------------------------------------------------------------------

class TaxiiEnvelope(BaseModel):
    """OASIS TAXII 2.1 §5.4 — Objects response envelope.

    'more' MUST be present even when False.
    'next' MUST be omitted (not null) when more=False — use model_post_init exclusion.
    """
    model_config = ConfigDict(populate_by_name=True)

    more: bool = False
    next: str | None = None
    objects: list[dict] = Field(default_factory=list)

    def model_dump(self, **kwargs):
        d = super().model_dump(**kwargs)
        # TAXII spec: omit 'next' key entirely when no more pages
        if not d.get("more"):
            d.pop("next", None)
        return d


# ---------------------------------------------------------------------------
# Admin schemas for taxii_clients CRUD (TAXII-03)
# ---------------------------------------------------------------------------

class TaxiiClientCreate(BaseModel):
    """Request body for POST /api/admin/taxii-clients."""
    label: str
    project_id: uuid.UUID
    tlp_max_level: str = "green"
    rate_limit_rpm: int = 60


class TaxiiClientRead(BaseModel):
    """Response for GET /api/admin/taxii-clients/{id}."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    project_id: uuid.UUID
    tlp_max_level: str
    rate_limit_rpm: int
    revoked: bool
    revoked_at: datetime | None
    created_at: datetime
    # NOTE: api_key_hash is NEVER returned; raw key returned once on create only


class TaxiiClientCreated(TaxiiClientRead):
    """Response for POST /api/admin/taxii-clients — includes raw key once."""
    raw_api_key: str  # shown once; not stored
