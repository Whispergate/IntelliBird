"""AuditLog ORM model - AUDIT-01, AUDIT-02.

Schema mirrors alembic 026_threat_actors_campaigns_audit.

Design notes:
  * audit_log is a TimescaleDB hypertable partitioned by 'time'.
  * Composite PK (time, id): TimescaleDB requires the partition column to appear
    in all unique constraints - same pattern as events (observed_at, id).
  * project_id is a nullable FK so audit rows can exist without a project context
    (e.g. admin actions).
  * before_jsonb / after_jsonb carry the diff snapshot; the audit service helper
    populates them selectively.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class AuditLog(Base):
    """Append-only audit log row (TimescaleDB hypertable).

    Never UPDATE or DELETE rows from this table - TimescaleDB retention policy
    handles expiry after 365 days.
    """

    __tablename__ = "audit_log"

    # Composite PK - time first (partition column), then id.
    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now()
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_sub: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    before_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
