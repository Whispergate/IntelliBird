"""AI infrastructure ORM models — Phase 17 / AI-01, AI-02, AI-03.

Three models for the LLM subsystem:

  AIProvider  — per-project LLM provider config with AES-256-GCM encrypted
                credentials. Mirrors sources.credentials_enc + credentials_key_version
                pattern exactly (Phase 03 / migration 007).

  AISummary   — LLM-generated summaries for individual events (summary_type='event')
                and daily project digests (summary_type='digest'). event_id is a soft
                UUID (no FK to events hypertable — same constraint as
                EventScoreOverride.event_id from Phase 15 / migration 013 and
                BrandMatch.event_id from Phase 12 / migration 011).

  AISuggestion — Analyst-gated entity extraction staging. LLM proposes CVE IDs,
                 ATT&CK technique IDs, or threat-actor names; analyst confirms or
                 discards. status: pending → confirmed | discarded.
                 decided_by_user_id FK (SET NULL) preserves audit trail after user
                 deletion.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, Text, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AIProvider(Base):
    """Per-project LLM provider configuration.

    Phase 17 / AI-01. One row per project (UNIQUE constraint on project_id).
    credentials_enc + credentials_key_version mirror sources.credentials_enc
    exactly — AES-256-GCM encryption via app.crypto. Encrypted at write time,
    decrypted at read time inside the AI router.

    api_base is required for Ollama (e.g. 'http://localhost:11434'); NULL for
    hosted providers (OpenAI / Anthropic) where the LiteLLM SDK derives the
    base URL from the provider_type.

    Added by migration 014_ai.
    """

    __tablename__ = "ai_providers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    provider_type: Mapped[str] = mapped_column(
        PgEnum("ollama", "openai", "anthropic", name="ai_provider_type_enum", create_type=False),
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    # Ollama base URL (e.g. 'http://ollama:11434'); NULL for hosted providers.
    api_base: Mapped[str | None] = mapped_column(Text, nullable=True)
    # AES-256-GCM encrypted credentials JSON blob — mirrors sources.credentials_enc.
    # NULL for credential-less providers (e.g. Ollama with no auth).
    credentials_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Monotonic key-version counter for credential rotation. Bumped by the
    # rekey-credentials endpoint on each rotation sweep.
    credentials_key_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class AISummary(Base):
    """LLM-generated summary record.

    Phase 17 / AI-02. Created for individual event summarisation
    (summary_type='event', event_id=UUID) and daily project digests
    (summary_type='digest', event_id=NULL).

    event_id is a soft UUID — NO FK constraint to events.id. Events is a
    TimescaleDB hypertable and CANNOT be a FK target (same pattern as
    EventScoreOverride.event_id in migration 013 and BrandMatch.event_id in
    migration 011). The application layer enforces the relationship.

    project_id FK (CASCADE) is the hard project scope boundary for PROD-01.

    requires_analyst_review defaults to true for event summaries; false for
    digest summaries (digests do not promote entities, so no analyst gate needed).

    Added by migration 014_ai.
    """

    __tablename__ = "ai_summaries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Soft FK to events.id — no DB constraint (events is a hypertable).
    # NULL for digest summaries (summary_type='digest').
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    summary_type: Mapped[str] = mapped_column(
        PgEnum("event", "digest", name="ai_summary_type_enum", create_type=False),
        nullable=False,
    )
    provider_used: Mapped[str] = mapped_column(Text, nullable=False)
    model_used: Mapped[str] = mapped_column(Text, nullable=False)
    # Records which prompt constant was used (e.g. 'EVENT_SUMMARY_PROMPT_V1').
    prompt_template_version: Mapped[str] = mapped_column(Text, nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_used: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    # true for event summaries (analyst must review suggestions); false for digest.
    requires_analyst_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class AISuggestion(Base):
    """Analyst-gated entity extraction staging row.

    Phase 17 / AI-03. The LLM proposes CVE IDs, ATT&CK technique IDs, or
    threat-actor names extracted from an event. Each suggestion requires explicit
    analyst confirmation (status='confirmed') or rejection (status='discarded')
    before any downstream action is taken. Auto-promote is NEVER allowed (C-2).

    ai_summary_id FK (CASCADE) links each suggestion to the summary that generated
    it; deleting the summary purges its suggestions.

    event_id is a soft UUID — no FK to the events hypertable (same pattern as
    AISummary.event_id). project_id FK (CASCADE) provides a direct project scope
    column without joining through ai_summaries.

    decided_by_user_id FK (SET NULL) preserves the audit trail when a user account
    is deleted — the decision record survives, the user reference becomes NULL.

    Added by migration 014_ai.
    """

    __tablename__ = "ai_suggestions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    ai_summary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_summaries.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Soft FK to events.id — no DB constraint (events is a hypertable).
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    suggestion_type: Mapped[str] = mapped_column(
        PgEnum("cve", "attack", "actor", name="ai_suggestion_type_enum", create_type=False),
        nullable=False,
    )
    # The extracted value: CVE ID string, ATT&CK technique ID, or actor name.
    value: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        PgEnum(
            "pending", "confirmed", "discarded",
            name="ai_suggestion_status_enum",
            create_type=False,
        ),
        nullable=False,
        server_default="pending",
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    # FK (SET NULL) — preserves audit trail when the deciding user account is deleted.
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
