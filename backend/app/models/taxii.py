"""TaxiiClient ORM model — Phase 26 / TAXII-03.

Stores per-partner API keys for the TAXII 2.1 outbound server.
Raw API keys are NEVER stored — only SHA-256 hex digest.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TaxiiClient(Base):
    __tablename__ = "taxii_clients"
    __table_args__ = (UniqueConstraint("api_key_hash", name="uq_taxii_clients_api_key_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    label: Mapped[str] = mapped_column(Text(), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(Text(), nullable=False, unique=True, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tlp_max_level: Mapped[str] = mapped_column(
        Text(), nullable=False, server_default="green"
    )
    rate_limit_rpm: Mapped[int] = mapped_column(
        Integer(), nullable=False, server_default="60"
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, server_default="false"
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
