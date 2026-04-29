"""BrandTerm + BrandMatch ORM — Phase 12 / BRP-01..BRP-05.

Maps to brand_terms and brand_matches tables created in migration 011.

Enum fields are typed as `str` on the ORM side (Phase 11 / easm.py precedent) —
Pydantic Literal types in `app.schemas.brand` provide compile-time + API-layer
validation; the PG enum enforces the storage invariant.

brand_matches.event_id has NO FK to events.id (events is a TimescaleDB hypertable;
hypertables cannot be FK targets). Soft reference; app enforces integrity.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class BrandTerm(Base):
    """A watched brand keyword/domain/product/person per project."""

    __tablename__ = "brand_terms"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    term_type: Mapped[str] = mapped_column(
        PgEnum(
            "keyword", "domain", "product", "person",
            name="brand_term_type", create_type=False,
        ),
        nullable=False,
    )
    value: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(
        PgEnum(
            "active", "watch_only",
            name="brand_term_mode", create_type=False,
        ),
        nullable=False,
        default="active",
    )
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    high_noise_risk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class BrandMatch(Base):
    """A single brand-term hit (fts / ct_log / dnstwist)."""

    __tablename__ = "brand_matches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    brand_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("brand_terms.id", ondelete="CASCADE"),
        nullable=False,
    )
    matched_value: Mapped[str] = mapped_column(Text, nullable=False)
    match_source: Mapped[str] = mapped_column(
        PgEnum(
            "fts", "ct_log", "dnstwist",
            name="brand_match_source", create_type=False,
        ),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        PgEnum(
            "low", "medium", "high",
            name="brand_match_severity", create_type=False,
        ),
        nullable=False,
    )
    first_seen: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    match_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Soft reference (see note in migration 011) — no FK to events hypertable.
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(
        PgEnum(
            "new", "confirmed", "dismissed", "watchlist",
            name="brand_match_lifecycle_status", create_type=False,
        ),
        nullable=False,
        default="new",
    )
    dismiss_until: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    webhook_fired_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )


class BrandStoplistTerm(Base):
    """Per-project stoplist term — Phase 21 / BRAND-01.

    Operator-managed additive union with global DEFAULT_STOPLIST + env extras.
    Uniqueness enforced case-insensitively via DB index on lower(term).
    """

    __tablename__ = "brand_stoplist_terms"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    term: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
