"""IOC + IOCEventLink ORM models — IOC-01, IOC-08.

Schema mirrors alembic 023 (revision id `019_iocs`). All ENUM columns use
`create_type=False` so SQLAlchemy never attempts CREATE TYPE — the migration
is the single source of truth for the type DDL.

Design notes:
  * `project_id` is NULLABLE — NULL = global "known bad" row visible to all
    projects (admin-curated). Per-project rows remain isolated.
  * Uniqueness `(project_id, type, normalized_value) NULLS NOT DISTINCT`
    is enforced at the index level (see migration 023). The model carries
    no `__table_args__` UNIQUE because SQLAlchemy core does not yet support
    NULLS NOT DISTINCT in `UniqueConstraint`.
  * `IOCEventLink.event_id` is a SOFT FK (no constraint) — `events` is a
    TimescaleDB hypertable; mirrors brand_matches.event_id precedent.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base

# Locked at migration 023 — extending requires a new alembic revision.
IOC_TYPES = (
    "ip", "ipv6", "domain", "url", "sha256", "sha1", "md5",
    "email", "btc", "eth", "mutex", "registry_key", "filename",
)
IOC_STATUSES = ("active", "expired", "whitelisted")
IOC_SOURCES = ("manual", "csv", "json", "stix", "event", "backfill", "misp")


class IOC(Base):
    """Atomic indicator (IOC-01)."""

    __tablename__ = "iocs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
    )
    type: Mapped[str] = mapped_column(
        PgEnum(*IOC_TYPES, name="ioc_type_enum", create_type=False),
        nullable=False,
    )
    value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        PgEnum(*IOC_STATUSES, name="ioc_status_enum", create_type=False),
        nullable=False,
        default="active",
    )
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=Decimal("0.7")
    )
    ttl_days: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(
        PgEnum(*IOC_SOURCES, name="ioc_source_enum", create_type=False),
        nullable=False,
        default="manual",
    )
    first_seen: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    event_links: Mapped[list["IOCEventLink"]] = relationship(
        back_populates="ioc",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class IOCEventLink(Base):
    """M2M junction between iocs and events (IOC-08).

    SOFT FK on event_id — events is a TimescaleDB hypertable.
    """

    __tablename__ = "ioc_event_links"
    __table_args__ = (
        UniqueConstraint("ioc_id", "event_id", name="uq_ioc_event_links_ioc_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ioc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("iocs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Soft reference — no FK constraint to events hypertable.
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    source_field: Mapped[str | None] = mapped_column(Text, nullable=True)

    ioc: Mapped["IOC"] = relationship(back_populates="event_links")


__all__ = ["IOC", "IOCEventLink", "IOC_TYPES", "IOC_STATUSES", "IOC_SOURCES"]
