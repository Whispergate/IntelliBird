"""EASM ORM models — mirrors migration 010_easm.py exactly.

Phase 11 / EASM-01, EASM-02, EASM-04, EASM-06, EASM-10.

EASMScan — one row per scan launch, FK → projects (CASCADE)
EASMFinding — deduped across scans via UNIQUE(project_id, bbot_event_type, canonical_target) (M-4)
EASMCredential — per-project provider credentials (encrypted, Phase 8 key-rotation pattern)
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    LargeBinary,
    TIMESTAMP,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM as PgEnum, JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


# ---------------------------------------------------------------------------
# Enum type objects — create_type=False because enums are pre-created by the
# migration 010 DO-block pattern (Phase 3/009 precedent). SA must not emit
# CREATE TYPE; postgresql.ENUM with create_type=False is the correct SA2 pattern.
# ---------------------------------------------------------------------------
EASM_SCAN_STATUS = PgEnum(
    "queued", "running", "finished", "failed", "cancelled", "orphaned",
    name="easm_scan_status", create_type=False,
)
EASM_SCAN_MODE = PgEnum(
    "passive", "active",
    name="easm_scan_mode", create_type=False,
)
EASM_SEVERITY = PgEnum(
    "low", "medium", "high", "critical",
    name="easm_severity", create_type=False,
)
EASM_LIFECYCLE = PgEnum(
    "new", "confirmed", "dismissed", "watchlist",
    name="easm_lifecycle", create_type=False,
)
EASM_CREDENTIAL_PROVIDER = PgEnum(
    "shodan", "github", "bevigil", "chaos", "securitytrails",
    name="easm_credential_provider", create_type=False,
)


class EASMScan(Base):
    """One row per BBOT scan launch for a project."""

    __tablename__ = "easm_scans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(EASM_SCAN_STATUS, nullable=False, default="queued")
    scan_mode = Column(EASM_SCAN_MODE, nullable=False)
    modules = Column(ARRAY(Text), nullable=False)
    container_id = Column(Text, nullable=True)
    started_at = Column(TIMESTAMP(timezone=True), nullable=False)
    finished_at = Column(TIMESTAMP(timezone=True), nullable=True)
    stdout_bytes = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    # Authentik sub of the user who launched the scan
    launched_by = Column(Text, nullable=False)

    findings = relationship(
        "EASMFinding",
        back_populates="scan",
        cascade="all, delete-orphan",
    )


class EASMFinding(Base):
    """Individual BBOT finding, deduped across scans by (project_id, bbot_event_type, canonical_target).

    M-4: ON CONFLICT DO UPDATE on the unique key updates last_seen + raw_bbot in place.
    H-4: NOT a TimescaleDB hypertable — plain partitioned table; no time-series overhead.
    """

    __tablename__ = "easm_findings"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "bbot_event_type", "canonical_target",
            name="uq_easm_findings_dedup",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    scan_id = Column(
        UUID(as_uuid=True),
        ForeignKey("easm_scans.id", ondelete="CASCADE"),
        nullable=False,
    )
    bbot_event_type = Column(Text, nullable=False)
    canonical_target = Column(Text, nullable=False)
    severity = Column(EASM_SEVERITY, nullable=True)
    module = Column(Text, nullable=False)
    raw_bbot = Column(JSONB, nullable=False)
    # sha256(project_id::text || bbot_event_type || canonical_target) — no scan_id/timestamp
    content_hash = Column(Text, nullable=False)
    first_seen = Column(TIMESTAMP(timezone=True), nullable=False)
    last_seen = Column(TIMESTAMP(timezone=True), nullable=False)
    lifecycle_status = Column(EASM_LIFECYCLE, nullable=False, default="new")
    dismiss_until = Column(TIMESTAMP(timezone=True), nullable=True)

    scan = relationship("EASMScan", back_populates="findings")


class EASMCredential(Base):
    """Per-project provider credentials (encrypted with Phase 8 key-rotation pattern)."""

    __tablename__ = "project_easm_credentials"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "provider",
            name="uq_project_easm_credentials_provider",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider = Column(EASM_CREDENTIAL_PROVIDER, nullable=False)
    credentials_enc = Column(LargeBinary, nullable=False)
    credentials_key_version = Column(Integer, nullable=False, default=1)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False)
