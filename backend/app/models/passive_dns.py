"""ORM models for passive DNS and WHOIS data — ENRICH-06..07."""
from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import List, Optional

from sqlalchemy import DateTime, Date, ForeignKey, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PassiveDnsRecord(Base):
    """One historical A/AAAA resolution for a domain IOC.

    Multiple rows per IOC (one per (ip, source) tuple returned by provider).
    ioc_id FK cascades on delete so records purge when the IOC is removed.
    """

    __tablename__ = "passive_dns_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ioc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("iocs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ip: Mapped[str] = mapped_column(Text(), nullable=False)
    first_seen: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source: Mapped[str] = mapped_column(Text(), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class WhoisCache(Base):
    """Cached WHOIS registration data for a domain (one row per domain).

    fetched_at drives the 7-day refetch suppression gate:
        WHERE fetched_at + INTERVAL '7 days' > now()
    means "still fresh — skip network call".
    """

    __tablename__ = "whois_cache"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    domain: Mapped[str] = mapped_column(Text(), nullable=False, unique=True)
    raw_json: Mapped[Optional[dict]] = mapped_column(JSONB(), nullable=True)
    registrar: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    registrant_email: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    registration_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date(), nullable=True)
    nameservers: Mapped[Optional[List[str]]] = mapped_column(
        ARRAY(Text()), nullable=True
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
