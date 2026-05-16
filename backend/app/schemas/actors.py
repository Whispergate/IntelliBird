"""Pydantic v2 schemas for actor, campaign, and audit log endpoints — Phase 25 / ACTOR-05, ACTOR-06, AUDIT-03."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Actor schemas
# ---------------------------------------------------------------------------


class ActorBase(BaseModel):
    primary_name: str
    aliases: list[str] | None = None
    country: str | None = None
    motivation: str | None = None
    sophistication: str | None = None
    first_seen: datetime | None = None
    profile_md: str | None = None


class ActorCreate(ActorBase):
    pass


class ActorPatch(BaseModel):
    primary_name: str | None = None
    aliases: list[str] | None = None
    country: str | None = None
    motivation: str | None = None
    sophistication: str | None = None
    first_seen: datetime | None = None
    profile_md: str | None = None


class ActorRead(ActorBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    mitre_group_id: str | None = None
    last_bootstrap_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ActorListResponse(BaseModel):
    items: list[ActorRead]
    next_cursor: str | None = None
    total: int | None = None


# ---------------------------------------------------------------------------
# Campaign schemas
# ---------------------------------------------------------------------------


class CampaignBase(BaseModel):
    name: str
    actor_id: uuid.UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    summary_md: str | None = None
    project_id: uuid.UUID | None = None  # None = global


class CampaignCreate(CampaignBase):
    pass


class CampaignPatch(BaseModel):
    name: str | None = None
    actor_id: uuid.UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    summary_md: str | None = None


class CampaignRead(CampaignBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_by_user_sub: str | None = None
    created_at: datetime
    updated_at: datetime


class CampaignListResponse(BaseModel):
    items: list[CampaignRead]
    next_cursor: str | None = None


# ---------------------------------------------------------------------------
# Audit log schemas
# ---------------------------------------------------------------------------


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    time: datetime
    user_sub: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    project_id: uuid.UUID | None = None
    before_jsonb: dict | None = None
    after_jsonb: dict | None = None
    request_id: str | None = None


class AuditLogListResponse(BaseModel):
    items: list[AuditLogRead]
    next_cursor: str | None = None
