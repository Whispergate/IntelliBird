"""Source registry. adds CRUD; establishes the schema."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Enum, Integer, TIMESTAMP, Text, text
from sqlalchemy.dialects.postgresql import UUID
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
