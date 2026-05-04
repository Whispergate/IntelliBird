"""ORM model for Phase 29: SigmaRule (stored Sigma detection rules).

Design notes:
  * Mirrors YaraRule shape from Phase 27 with two key differences:
    - No family field (Sigma rules do not have a family taxonomy)
    - compiled_cache is JSONB (not LargeBinary) — Sigma compilation produces
      a Python dict (field mappings, detection conditions) rather than binary
  * SigmaRule.project_id is nullable — NULL = global rule visible to all projects
    (admin-curated). Per-project rules are scoped by project_id filter.
  * level (TEXT, nullable) mirrors Sigma's native severity:
    informational | low | medium | high | critical
  * tags (ARRAY of TEXT, nullable) stores raw Sigma rule tags such as
    attack.t1566 — written to attack_technique_tags on event matches.
  * No SigmaMatch join table — Sigma writes directly to attack_technique_tags
    on the matched event rows (see Phase 29 scanner design in 29-CONTEXT.md).
"""
from __future__ import annotations

import uuid
import datetime

from sqlalchemy import Boolean, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID as pg_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SigmaRule(Base):
    """Stored Sigma detection rule — global (project_id IS NULL) or per-project."""

    __tablename__ = "sigma_rules"

    id: Mapped[uuid.UUID] = mapped_column(pg_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Internal — JSONB cache of the compiled rule; NOT exposed in API read schemas
    compiled_cache: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Sigma native severity: informational | low | medium | high | critical
    level: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Raw Sigma tags e.g. ["attack.t1566", "attack.phishing"] — drives ATT&CK tagging
    tags: Mapped[list | None] = mapped_column(ARRAY(Text), nullable=True)
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
