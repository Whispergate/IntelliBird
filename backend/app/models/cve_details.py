"""CveDetails — INGC-02 indexed CVE-specific columns, keyed on event_id.

No FK to events: events is a TimescaleDB hypertable (PITFALLS H-7-adjacent
constraint from Phase 1). App-level integrity only, same as
attack_technique_tags.event_id.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Double, TIMESTAMP, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CveDetails(Base):
    __tablename__ = "cve_details"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    cve_id: Mapped[str] = mapped_column(Text, nullable=False)
    cvss_v3_score: Mapped[float | None] = mapped_column(Double, nullable=True)
    cvss_v3_vector: Mapped[str | None] = mapped_column(Text, nullable=True)
    cpe_match: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    cwe_ids: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    last_modified: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
