"""TLP marking definitions (canonical UUIDs hard-coded - see migration 001)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TlpMarking(Base):
    __tablename__ = "tlp_markings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    stix_definition_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="tlp")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
