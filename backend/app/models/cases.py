"""ORM models for Phase 31 Case Management — CASE-01, CASE-02.

Tables: cases, case_events, case_iocs
ENUMs: case_status_enum, case_severity_enum (created in migration 032_cases)

Design notes:
  * CaseEvent.event_id is a Soft FK — events is a TimescaleDB hypertable;
    real FK constraints are not supported against hypertables. Same precedent
    as CampaignEvent.event_id (actors.py) and IOCEventLink.event_id (iocs.py).
  * CaseIOC.ioc_id is a Hard FK — iocs is a regular PostgreSQL table; FK constraint
    is safe and enforces referential integrity.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base


class CaseStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    on_hold = "on_hold"
    resolved = "resolved"
    closed = "closed"


class CaseSeverity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Case(Base):
    """Per-project investigation case with lifecycle status and severity."""

    __tablename__ = "cases"
    __table_args__ = (
        Index("ix_cases_project_id", "project_id"),
        Index("ix_cases_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    severity: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee_user_sub: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    events: Mapped[list["CaseEvent"]] = relationship(
        "CaseEvent", back_populates="case", cascade="all, delete-orphan"
    )
    iocs: Mapped[list["CaseIOC"]] = relationship(
        "CaseIOC", back_populates="case", cascade="all, delete-orphan"
    )


class CaseEvent(Base):
    """M2M junction: case ↔ event.

    event_id is a Soft FK — events is a TimescaleDB hypertable and cannot carry
    real FK constraints. Same pattern as CampaignEvent and IOCEventLink.
    """

    __tablename__ = "case_events"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Soft FK — NO ForeignKey("events.id") — events is a TimescaleDB hypertable.
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    attached_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    attached_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    case: Mapped["Case"] = relationship("Case", back_populates="events")


class CaseIOC(Base):
    """M2M junction: case ↔ ioc.

    ioc_id is a Hard FK — iocs is a regular PostgreSQL table (not a hypertable),
    so a FK constraint is safe and enforces referential integrity.
    """

    __tablename__ = "case_iocs"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Hard FK — iocs is NOT a hypertable; ForeignKey() constraint is safe.
    ioc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("iocs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    attached_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    attached_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    case: Mapped["Case"] = relationship("Case", back_populates="iocs")
