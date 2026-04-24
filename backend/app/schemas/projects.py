"""Pydantic v2 schemas for projects, scope rows, memberships, source-binding — Phase 10.

Exports request/response models consumed by the upcoming project CRUD router
(plan 10-03), scope router (plan 10-04), memberships router (plan 10-02/10-03),
and source-binding router (plan 10-04).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EngagementTypeLit = Literal["red_team", "tiber", "bbest", "internal", "intel_only"]
ScopeTypeLit = Literal["keyword", "service", "domain", "certificate", "whois", "as_number", "ip_range"]
ProjectRoleLit = Literal["Lead", "Contributor", "Observer"]


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    engagement_type: EngagementTypeLit
    description: str | None = Field(default=None, max_length=2000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    engagement_type: EngagementTypeLit | None = None
    description: str | None = Field(default=None, max_length=2000)
    archived: bool | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    engagement_type: EngagementTypeLit
    description: str | None
    created_by: str
    archived: bool
    active_scans_authorised: bool
    scope_acknowledgement_text: str | None
    active_auth_confirmed_at: datetime | None
    active_auth_confirmed_by: str | None = None
    created_at: datetime
    updated_at: datetime
    # Hydrated by router (LEFT JOIN project_memberships; current-user compare):
    member_count: int = 0
    creator_is_current_user: bool = False


# ---------------------------------------------------------------------------
# ScopeRow
# ---------------------------------------------------------------------------

class ScopeRowCreate(BaseModel):
    scope_type: ScopeTypeLit
    value: str = Field(min_length=1, max_length=1024)
    contact: str | None = Field(default=None, max_length=400)
    exclude: bool = False
    active_test_scope: bool = False
    intel_scope: bool = True

    @model_validator(mode="after")
    def _at_least_one_flag(self) -> "ScopeRowCreate":
        if not (self.active_test_scope or self.intel_scope):
            raise ValueError("Row must target at least intel or active test.")
        return self


class ScopeRowUpdate(BaseModel):
    contact: str | None = Field(default=None, max_length=400)
    exclude: bool | None = None
    active_test_scope: bool | None = None
    intel_scope: bool | None = None

    @model_validator(mode="after")
    def _at_least_one_flag_if_both_set(self) -> "ScopeRowUpdate":
        # Validate only when BOTH flags appear in the update body and both are false.
        if self.active_test_scope is False and self.intel_scope is False:
            raise ValueError("Row must target at least intel or active test.")
        return self


class ScopeRowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    scope_type: ScopeTypeLit
    value: str
    contact: str | None
    exclude: bool
    active_test_scope: bool
    intel_scope: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------

class MembershipCreate(BaseModel):
    user_sub: str = Field(min_length=1, max_length=400)
    project_role: ProjectRoleLit


class MembershipUpdate(BaseModel):
    project_role: ProjectRoleLit


class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    user_sub: str
    project_role: ProjectRoleLit
    added_by: str | None
    created_at: datetime
    # Hydrated by /api/auth/memberships (router does JOIN projects to fill this):
    project_name: str | None = None


# ---------------------------------------------------------------------------
# project_sources binding
# ---------------------------------------------------------------------------

class ProjectSourcesBinding(BaseModel):
    """Body of PUT /api/projects/{id}/sources.

    Empty list = remove all bindings (fallback to "all sources visible").
    """

    source_ids: list[uuid.UUID]
