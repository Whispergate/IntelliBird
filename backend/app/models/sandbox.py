"""ORM models for SandboxConfig (per-project provider config) and SandboxReport (hypertable).

Design notes:
  * SandboxReport uses a composite PRIMARY KEY (id, submitted_at) as required by
    TimescaleDB for hypertables — the partition column must appear in all unique constraints.
  * SandboxReport.event_id is a SOFT FK (no ForeignKey clause) — events is a
    TimescaleDB hypertable; real FK constraints are not supported against hypertables.
    Nullable because a report may be triggered from a bare IOC with no event link.
  * SandboxConfig.project_id has UNIQUE so there is exactly one config per project.
  * api_key_enc stores the encrypted API key; plaintext is never persisted.
"""
from __future__ import annotations

import uuid
import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, Text, ARRAY, text
from sqlalchemy.dialects.postgresql import UUID as pg_UUID, JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SandboxConfig(Base):
    """Per-project sandbox provider configuration (one row per project)."""

    __tablename__ = "sandbox_configs"

    id: Mapped[uuid.UUID] = mapped_column(pg_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), unique=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    public_warning_acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    options: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class SandboxReport(Base):
    """Detonation report — TimescaleDB hypertable partitioned on submitted_at.

    Composite PK (id, submitted_at): TimescaleDB requires the partition column
    to appear in all unique constraints — same pattern as events (observed_at, id)
    and audit_log (time, id).

    event_id is a SOFT FK — events is a hypertable, real FK not supported.
    poll_attempts is load-bearing for SANDBOX-03 timeout / back-off logic.
    """

    __tablename__ = "sandbox_reports"

    # Composite PK — id first for natural lookup, submitted_at second (partition column)
    id: Mapped[uuid.UUID] = mapped_column(pg_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submitted_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), primary_key=True, nullable=False, server_default=text("now()")
    )
    # SOFT FK — events is a hypertable, real FK not supported; nullable when IOC has no event link
    event_id: Mapped[uuid.UUID | None] = mapped_column(pg_UUID(as_uuid=True), nullable=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    job_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    report_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    techniques: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    network_iocs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    process_tree: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    poll_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
