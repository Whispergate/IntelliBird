"""Pydantic schemas for sources - DARK-07 extension."""
from __future__ import annotations

from pydantic import BaseModel


class SourceDarkWebExtension(BaseModel):
    """Fields added in. Included in create/update/response schemas."""

    opsec_authorised: bool = False
    # session_enc is write-only - never serialised in GET responses to avoid
    # leaking ciphertext. Set on create/update for telegram source types only.
    session_enc: str | None = None
