"""Pydantic v2 schemas for Case Management API — CASE-01, CASE-02."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CaseCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: str
    severity: str | None = None
    assignee_user_sub: str | None = None
    description: str | None = None


class CasePatch(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: str | None = None
    status: str | None = None
    severity: str | None = None
    assignee_user_sub: str | None = None
    description: str | None = None
    summary_md: str | None = None
    closed_at: datetime | None = None


class CaseRead(CaseCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    summary_md: str | None = None
    opened_at: datetime
    closed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CaseListResponse(BaseModel):
    items: list[CaseRead]
    total: int


class CaseEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    case_id: uuid.UUID
    event_id: uuid.UUID
    attached_at: datetime
    attached_by: str | None = None


class CaseIOCRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    case_id: uuid.UUID
    ioc_id: uuid.UUID
    attached_at: datetime
    attached_by: str | None = None


class CaseActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: str
    user_sub: str | None = None
    time: datetime
    after_jsonb: dict | None = None


class AttachEventsRequest(BaseModel):
    event_ids: list[uuid.UUID]


class AttachIOCsRequest(BaseModel):
    ioc_ids: list[uuid.UUID]
