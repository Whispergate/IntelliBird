"""FilterPreset ORM — FIL-04 saved filter presets.

Maps to the filter_presets table created in migration 004_fts_and_presets.
Name is globally unique (no auth in M1 single-tenant).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, TIMESTAMP, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FilterPreset(Base):
    """Saved filter preset — stores query_params dict for /api/events replay."""

    __tablename__ = "filter_presets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # Phase 10 / PRJ-01 — every preset pins to a project. Pre-Phase-10 rows
    # carry LEGACY_PROJECT_ID; new rows must pass project_id explicitly.
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    query_params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
