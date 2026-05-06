"""MispConfig ORM model — Phase 32 MISP bidirectional sync.

One row per project. API key stored AES-256-GCM via app.crypto.encrypt_credentials.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class MispConfig(Base):
    """Per-project MISP configuration and credential storage."""

    __tablename__ = "misp_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_enc: Mapped[str] = mapped_column(Text, nullable=False)
    pull_tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    push_types: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ssl_verify: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[object] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[object] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


__all__ = ["MispConfig"]
