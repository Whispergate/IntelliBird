"""ORM models for the threat-actor / campaign subsystem — Phase 25 / ACTOR-01, ACTOR-03.

Schema mirrors alembic 026_threat_actors_campaigns_audit.

Design notes:
  * ThreatActor.aliases is a PostgreSQL ARRAY(Text) column — nullable.
  * ThreatActor.mitre_group_id has a partial unique index (see migration 026) so it is
    declared unique=True here for SQLAlchemy introspection; the partial index in the DB
    is the authoritative constraint.
  * CampaignEvent.event_id and ActorEventLink.event_id are SOFT FKs (no ForeignKey
    constraint) — events is a TimescaleDB hypertable; real FK constraints are not
    supported against hypertables.
  * country, motivation, sophistication are NOT standard STIX fields. Nullable, analyst-
    editable only — never populated from automated bootstrap.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import ARRAY, Date, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base


class ThreatActor(Base):
    """Global threat-actor registry entry (MITRE ATT&CK group or analyst-curated)."""

    __tablename__ = "threat_actors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    primary_name: Mapped[str] = mapped_column(Text, nullable=False)
    # Analyst-editable fields (NOT from STIX — nullable)
    aliases: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    country: Mapped[str | None] = mapped_column(Text, nullable=True)
    motivation: Mapped[str | None] = mapped_column(Text, nullable=True)
    sophistication: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    profile_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Partial unique index in DB; declared here for ORM introspection.
    mitre_group_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    last_bootstrap_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    campaigns: Mapped[list["Campaign"]] = relationship(
        "Campaign", back_populates="actor"
    )


class Campaign(Base):
    """Campaign linked to an optional actor and optional project."""

    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("threat_actors.id", ondelete="SET NULL"),
        nullable=True,
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    summary_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
    )
    created_by_user_sub: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    actor: Mapped["ThreatActor | None"] = relationship(
        "ThreatActor", back_populates="campaigns"
    )


class CampaignEvent(Base):
    """M2M junction: campaign ↔ event.

    event_id is a SOFT FK — events is a TimescaleDB hypertable and cannot carry
    real FK constraints.
    """

    __tablename__ = "campaign_events"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Soft FK — NO ForeignKey("events.id") — events is a hypertable.
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    linked_by_user_sub: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ActorEventLink(Base):
    """Auto-link from fuzzy actor-name match (rapidfuzz score ≥ 85).

    event_id is a SOFT FK — events is a TimescaleDB hypertable and cannot carry
    real FK constraints.
    """

    __tablename__ = "actor_event_links"

    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("threat_actors.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Soft FK — NO ForeignKey("events.id") — events is a hypertable.
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    linked_by: Mapped[str] = mapped_column(Text, nullable=False, default="auto")
