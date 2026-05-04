"""ORM models for Phase 27: YaraRule (stored rules) and YaraMatch (hit join table).

Design notes:
  * YaraRule.project_id is nullable — NULL = global rule visible to all projects
    (admin-curated). Per-project rules are isolated by project_id filter.
  * compiled_cache stores pre-compiled YARA bytea to avoid recompile on every scan.
    It is an internal binary column — never exposed in API read schemas.
  * YaraMatch.event_id is a SOFT FK (no ForeignKey clause) — events is a
    TimescaleDB hypertable; real FK constraints are not supported against hypertables.
  * scan_context distinguishes file-sample scans ('sample') from STIX-pattern
    matches ('stix_pattern'). UNIQUE (rule_id, event_id, scan_context) is enforced
    at the DB level (see migration 028).
"""
from __future__ import annotations

import uuid
import datetime

from sqlalchemy import Boolean, ForeignKey, LargeBinary, Text, text
from sqlalchemy.dialects.postgresql import UUID as pg_UUID, JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class YaraRule(Base):
    """Stored YARA rule — global (project_id IS NULL) or per-project."""

    __tablename__ = "yara_rules"

    id: Mapped[uuid.UUID] = mapped_column(pg_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    family: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Internal — bytea cache of the compiled rule; NOT exposed in API read schemas
    compiled_cache: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # NULL = global rule; non-NULL = scoped to this project
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class YaraMatch(Base):
    """M2M join between a YARA rule and an event.

    event_id is a SOFT FK — events is a hypertable, real FK not supported.
    UNIQUE (rule_id, event_id, scan_context) prevents duplicate match records.
    """

    __tablename__ = "yara_matches"

    id: Mapped[uuid.UUID] = mapped_column(pg_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("yara_rules.id", ondelete="CASCADE"))
    # SOFT FK — events is a hypertable, real FK not supported
    event_id: Mapped[uuid.UUID] = mapped_column(pg_UUID(as_uuid=True), nullable=False)
    matched_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    match_strings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    scan_context: Mapped[str] = mapped_column(Text, nullable=False, default="sample")  # 'sample' | 'stix_pattern'
