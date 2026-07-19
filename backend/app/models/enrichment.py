"""Enrichment ORM models - ENRICH-01, ENRICH-04.

EnrichmentProvider: per-project (project_id NOT NULL) or global
  (project_id IS NULL) API key config. Mirrors AIProvider shape from
  models/ai.py - same credentials_enc + credentials_key_version pattern.

IOCEnrichment: one row per (ioc_id, provider) result. raw_response_jsonb
  retains full API payload for future UI changes without re-fetching.
  verdict is the ioc_verdict ENUM. Upserted on re-enrichment.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, Text, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


_IOC_VERDICT = PgEnum(
    "clean", "suspicious", "malicious", "unknown",
    name="ioc_verdict",
    create_type=False,  # created by migration 024
)

PROVIDER_CHOICES = frozenset({"vt", "abuseipdb", "greynoise", "otx", "shodan", "urlhaus"})


class EnrichmentProvider(Base):
    """Per-project (or global) reputation provider configuration.

    project_id IS NULL → global default, inherited by any project without
    a per-project row when the global row has enabled=True.

    UNIQUE (project_id, provider) NULLS NOT DISTINCT enforced by migration 024
    index uq_enrichment_providers_project_provider.
    """

    __tablename__ = "enrichment_providers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    credentials_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    credentials_key_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    daily_request_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class IOCEnrichment(Base):
    """One enrichment result row per (ioc_id, provider).

    raw_response_jsonb retains the full provider API payload - allows
    re-rendering with new UI logic without re-fetching. On re-enrichment
    (POST /api/iocs/{id}/enrich), existing row is updated in-place via
    ON CONFLICT DO UPDATE.

    ioc_id FK CASCADE - deleting the IOC purges its enrichment rows.
    """

    __tablename__ = "ioc_enrichments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    ioc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("iocs.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    raw_response_jsonb: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    verdict: Mapped[str] = mapped_column(
        _IOC_VERDICT, nullable=False, server_default="unknown"
    )
    score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = ["EnrichmentProvider", "IOCEnrichment", "PROVIDER_CHOICES"]
