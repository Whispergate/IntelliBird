"""events hypertable + SYS-01 provenance columns + H-9 visibility enum."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Boolean, Double, Enum, ForeignKey, Integer, String, TIMESTAMP, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Event(Base):
    __tablename__ = "events"
    # Composite PK (id, observed_at) — TimescaleDB requires partition col in PK.
    __table_args__ = {}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    stix_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    stix_type: Mapped[str] = mapped_column(Text, nullable=False)
    # SYS-01 provenance columns — required on every event row:
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    # Phase 10 / PRJ-01 — every event carries a project_id. Pre-Phase-10 rows
    # point at LEGACY_PROJECT_ID (app.models.projects); new rows must pass
    # project_id explicitly (migration 009 dropped the DEFAULT).
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    fetched_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    raw_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, primary_key=True
    )  # hypertable partition key — part of composite PK
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tlp_marking_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # H-3 semantic dedup key:
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    geo_lat: Mapped[float | None] = mapped_column(Double, nullable=True)
    geo_lon: Mapped[float | None] = mapped_column(Double, nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    # H-9 Red/Blue isolation — enforce at query layer from day one:
    visibility: Mapped[str] = mapped_column(
        Enum("red_only", "blue_only", "shared", name="visibility_enum", create_type=False),
        nullable=False, server_default="shared",
    )
    raw_stix: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    # H-7 soft-delete for retention with attack-graph reference preservation:
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    # Phase 11 / EASM-06: provenance FK — L-4: ON DELETE SET NULL so promoted events
    # survive scan cleanup (scan delete does NOT cascade to events).
    easm_scan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("easm_scans.id", ondelete="SET NULL"),
        nullable=True,
    )
