"""Source registry. adds CRUD; establishes the schema."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, Numeric, TIMESTAMP, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    feed_type: Mapped[str] = mapped_column(
        Enum("rss", "taxii", "nvd", "custom", name="feed_type_enum", create_type=False),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    credentials_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    poll_interval_sec: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3600")
    hot_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    credentials_key_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_polled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    archive_policy: Mapped[str] = mapped_column(
        Enum(
            "keep", "drop", "move-to-cold",
            name="archive_policy_enum",
            create_type=False,
        ),
        nullable=False,
        server_default="drop",
    )
    silent_failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    # Phase 15 / SCR-01: feed source reliability weighting for score_event() function.
    # Backfilled by migration 013 per feed_type: taxii=1.0, nvd=1.0, rss=0.7.
    # Custom sources start NULL — ingest pipeline applies per-type defaults on first poll.
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    # Phase 16 / MON-01: SLA-based silence detection pivot. NULL = no event ever received
    # (itself a silence signal). Updated by all 4 ingest sites after successful insert.
    # Added by migration 016_monitoring.
    last_event_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    # Phase 16 / MON-02, MON-03: per-source monitoring threshold overrides as JSONB.
    # Empty {} means "use feed_type defaults" (see app.schemas.monitoring.MonitoringConfig).
    # Added by migration 016_monitoring.
    monitoring_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Quick task 260425-ovt: HTML-scrape selector config. Sparse — populated only
    # when feed_type='custom'. Schema validated by app.ingest.html_scrape_parser
    # .validate_scrape_config (item_selector / title_selector / link_selector
    # required). Added by migration 017_html_scrape.
    scrape_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class SourceIngestStats(Base):
    """Per-source ingest counter row written once per poll batch.

    Phase 16 / MON-03: item-level parse_ok/parse_error + batch-level fetch_ok/fetch_error
    counters. Workers accumulate these in-process during a poll and INSERT one row at
    completion via record_ingest_stats() in app.services.source_health.

    This is a TimescaleDB hypertable partitioned by 'time' (migration 016). The composite
    primary key (time, source_id) satisfies TimescaleDB's requirement that the time column
    be part of the PK. The ORM treats it as a regular table — hypertable semantics are
    fully transparent to SQLAlchemy.

    Note: source_ingest_stats cannot be a FK target (same limitation as events hypertable).
    Queries against this table always use the source_id column for filtering.
    """

    __tablename__ = "source_ingest_stats"

    time: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, primary_key=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    )
    parse_ok: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    parse_error: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    fetch_ok: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    fetch_error: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class MaintenanceWindow(Base):
    """Global maintenance window — suppresses all MON-01..03 monitoring alerts.

    Phase 16 / H-7: a single active window suspends silence, volume drift, and parse
    error rate alerts for the duration. 'Active' is defined as now() BETWEEN start_at AND
    end_at — no daemon required; windows auto-expire when end_at passes.

    created_by_user_id is nullable so programmatically created rows (e.g. API bootstrap)
    don't require a user context. ON DELETE SET NULL preserves window history after a user
    is deleted.

    Admin-only CRUD (enforced in the router via require_admin dependency).
    Added by migration 016_monitoring.
    """

    __tablename__ = "maintenance_windows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        nullable=False,
    )
    start_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
