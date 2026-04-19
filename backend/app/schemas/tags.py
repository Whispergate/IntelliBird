"""Pydantic schemas for tag PATCH — FIL-03."""
from __future__ import annotations

import re

from pydantic import BaseModel, field_validator

TAG_REGEX = re.compile(r"^[a-z0-9_-]{1,32}$")


class TagPatchRequest(BaseModel):
    add: list[str] = []
    remove: list[str] = []

    @field_validator("add", "remove", mode="after")
    @classmethod
    def _normalise_and_validate(cls, v: list[str]) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("must be a list of strings")
        out: list[str] = []
        for t in v:
            if not isinstance(t, str):
                raise ValueError(f"tag must be a string, got {type(t).__name__}")
            lowered = t.lower()
            if not TAG_REGEX.match(lowered):
                raise ValueError(
                    f"tag {t!r} does not match ^[a-z0-9_-]{{1,32}}$ "
                    f"(got {lowered!r} after lowercasing)"
                )
            out.append(lowered)
        return out


class TagPatchResponse(BaseModel):
    tags: list[str]
