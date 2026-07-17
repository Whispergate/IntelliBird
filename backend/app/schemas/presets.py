"""Pydantic schemas for filter presets — FIL-04."""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

PRESET_NAME_REGEX = re.compile(r"^[a-z0-9_-]{1,64}$")


class PresetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    project_id: uuid.UUID
    query_params: dict[str, Any]

    @field_validator("name", mode="after")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not PRESET_NAME_REGEX.match(v):
            raise ValueError(
                f"name {v!r} does not match ^[a-z0-9_-]{{1,64}}$"
            )
        return v


class PresetUpsert(BaseModel):
    query_params: dict[str, Any]
    project_id: uuid.UUID | None = None # optional on PUT (upsert preserves existing)


class FilterPresetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    project_id: uuid.UUID # included in responses
    query_params: dict[str, Any]
    created_at: datetime
    updated_at: datetime
