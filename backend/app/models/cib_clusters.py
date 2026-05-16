"""CIB cluster detection result — Phase 33 / DISINFO-02."""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Integer, Text, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CibCluster(Base):
    """Coordinated Inauthentic Behaviour cluster detected by the CIB detector worker.

    Each row represents a group of events (member_event_ids) that were flagged as
    part of a coordinated campaign by MinHashLSH similarity analysis. Rows are
    project-scoped; deleting the project cascades to all its clusters.

    severity is constrained to 'medium' or 'high' — low-confidence matches are
    filtered before insertion. evidence is a JSONB blob with detector metadata
    (e.g. similarity scores, representative hashes).

    Added by migration 034_social_listening.
    """

    __tablename__ = "cib_clusters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    detected_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
    )
    member_event_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False
    )
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    severity: Mapped[str] = mapped_column(
        Text,
        sa.CheckConstraint("severity IN ('medium','high')", name="ck_cib_severity"),
        nullable=False,
    )
