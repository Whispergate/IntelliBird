"""Pydantic v2 schemas for MISP config — MISP-01."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MispConfigBase(BaseModel):
    """Shared fields for MISP config create and update."""

    url: str = Field(..., description="MISP instance base URL, e.g. https://misp.example.com")
    pull_tags: list[str] = Field(default_factory=list, description="MISP tag/galaxy strings to pull")
    push_types: list[str] = Field(
        default_factory=list,
        description="Suggestion types to push: 'cve', 'attack', 'actor'",
    )
    enabled: bool = Field(default=True)
    ssl_verify: bool = Field(default=True, description="Verify MISP TLS certificate")


class MispConfigCreate(MispConfigBase):
    """Create request — requires api_key plaintext (will be encrypted at rest)."""

    api_key: str = Field(..., description="MISP API key (stored encrypted, never returned)")

    @field_validator("push_types")
    @classmethod
    def validate_push_types(cls, v: list[str]) -> list[str]:
        allowed = {"cve", "attack", "actor"}
        invalid = set(v) - allowed
        if invalid:
            raise ValueError(f"Invalid push_types: {invalid}. Allowed: {allowed}")
        return v


class MispConfigUpdate(BaseModel):
    """Partial update — all fields optional."""

    url: str | None = None
    api_key: str | None = Field(default=None, description="Provide to rotate the API key")
    pull_tags: list[str] | None = None
    push_types: list[str] | None = None
    enabled: bool | None = None
    ssl_verify: bool | None = None


class MispConfigRead(MispConfigBase):
    """Response schema — api_key_enc replaced with masked indicator."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    api_key_masked: str = Field("***", description="API key is stored encrypted; value always masked")


class MispTestConnectionRequest(BaseModel):
    """Request body for test-connection endpoint."""

    url: str
    api_key: str
    ssl_verify: bool = True


class MispTestConnectionResponse(BaseModel):
    """Response from test-connection."""

    ok: bool
    version: str | None = None
    error: str | None = None


__all__ = [
    "MispConfigCreate",
    "MispConfigUpdate",
    "MispConfigRead",
    "MispTestConnectionRequest",
    "MispTestConnectionResponse",
]
