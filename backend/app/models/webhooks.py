"""Webhook + WebhookPresetBinding ORM — maps to migration 006 tables.

: auth_enc is Text (not LargeBinary) — app.crypto returns base64url str.
: webhook_preset_bindings is a join table; composite PK (webhook_id, preset_name).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, TIMESTAMP, Text, text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Webhook(Base):
    """Outbound webhook destination — maps to webhooks table (migration 006)."""

    __tablename__ = "webhooks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    destination_type: Mapped[str] = mapped_column(
        PgEnum(
            "slack", "teams", "discord", "generic",
            name="destination_type_enum",
            create_type=False,  # created by migration 006 DO $$ block
        ),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    #: Text (base64url) — NOT LargeBinary.
    # app.crypto.encrypt_credentials returns a base64url string. Matches
    # the sources.credentials_enc pattern exactly.
    auth_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    batching_window_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="300"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    last_dispatch_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    last_delivery_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    last_delivery_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()")
    )


class WebhookPresetBinding(Base):
    """Join table: webhooks ↔ filter_presets. Composite PK."""

    __tablename__ = "webhook_preset_bindings"

    webhook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("webhooks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    preset_name: Mapped[str] = mapped_column(
        Text,
        ForeignKey("filter_presets.name", ondelete="CASCADE"),
        primary_key=True,
    )
