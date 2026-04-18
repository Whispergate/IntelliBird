"""ATT&CK technique tags on events — SYS-02 provenance fields."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Enum, Float, TIMESTAMP, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AttackTechniqueTag(Base):
    __tablename__ = "attack_technique_tags"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # NOTE: no FK to events.id — TimescaleDB hypertables can't be FK targets.
    # App-level integrity enforces the link.
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    technique_id: Mapped[str] = mapped_column(Text, nullable=False)
    # SYS-02 provenance:
    tag_source: Mapped[str] = mapped_column(
        Enum("feed_asserted", "analyst", "auto", name="tag_source_enum", create_type=False),
        nullable=False,
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
