"""Pydantic v2 schemas for events API — FIL-01, FIL-02."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FeedType = Literal["rss", "taxii", "nvd"]
TlpName = Literal["clear", "green", "amber", "amber+strict", "red"]
Visibility = Literal["shared", "red_only", "blue_only"]


class EventItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    observed_at: datetime
    fetched_at: datetime
    source_id: uuid.UUID | None
    source_name: str | None = None
    source_type: FeedType | None = None
    stix_id: str | None
    stix_type: str
    title: str | None
    description: str | None
    tlp: TlpName | None = None
    tags: list[str] = Field(default_factory=list)
    attack_techniques: list[str] = Field(default_factory=list)
    archived: bool
    visibility: Visibility
    geo_lat: float | None = None
    geo_lon: float | None = None


class EventDetail(EventItem):
    """Full event including raw_stix JSONB — returned by GET /api/events/{id}."""

    raw_stix: dict | None = None


class EventListResponse(BaseModel):
    items: list[EventItem]
    next_cursor: str | None
    total: int | None
