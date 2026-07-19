"""Pydantic v2 request/response models for /api/admin/users + /api/admin/setup.

AUTH-01, AUTH-02.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["Admin", "Analyst", "Viewer"]
DashboardRole = Literal["red", "blue"]


class SetupRequest(BaseModel):
    """POST /api/admin/setup body. Creates the first Admin."""

    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=12, max_length=512)


class UserCreate(BaseModel):
    """POST /api/admin/users body. Admin-initiated temp-password user."""

    username: str = Field(..., min_length=1, max_length=128)
    role: Role
    dashboard_roles: list[DashboardRole] = Field(default_factory=list)
    initial_password: str = Field(
        ...,
        min_length=12,
        max_length=512,
        description="Temp password; user forced to change on first login",
    )


class UserUpdate(BaseModel):
    """PATCH /api/admin/users/{id} body. All fields optional."""

    role: Role | None = None
    dashboard_roles: list[DashboardRole] | None = None
    enabled: bool | None = None


class UserResponse(BaseModel):
    """GET /api/admin/users list row + POST/PATCH /admin/users response."""

    id: str
    username: str
    role: Role
    dashboard_roles: list[str]
    enabled: bool
    must_change_password: bool
    locked: bool = False
    last_login_at: datetime | None = None
    created_at: datetime


class AdminResetPasswordRequest(BaseModel):
    """POST /api/admin/users/{id}/reset-password body."""

    new_password: str = Field(
        ...,
        min_length=12,
        max_length=512,
        description="Replacement password; user forced to change on next login",
    )


class SetupResponse(BaseModel):
    """POST /api/admin/setup response - subset of UserResponse (no enabled/locked)."""

    id: str
    username: str
    role: Role
    dashboard_roles: list[str]
    must_change_password: bool
