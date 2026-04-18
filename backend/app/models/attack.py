"""ATT&CK technique catalog (attack_techniques)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Enum, TIMESTAMP, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AttackTechnique(Base):
    __tablename__ = "attack_techniques"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    technique_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    tactic: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    matrix: Mapped[str] = mapped_column(
        Enum("enterprise", "ics", "mobile", name="matrix_enum", create_type=False),
        nullable=False,
    )
    stix_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_stix: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
