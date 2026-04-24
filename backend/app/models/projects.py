"""Project + ProjectScopeRow + ProjectSource + ProjectMembership ORM — Phase 10 / PRJ-01, PRJ-02, PRJ-05.

Exports the LEGACY_PROJECT_ID constant used by migration 009 and every downstream
test/router that needs to reference the sentinel row.

Role model note: project_role (Lead/Contributor/Observer) is ORTHOGONAL to global
role (Admin/Analyst/Viewer). Effective access = intersection. A user has exactly
one global role and zero-or-more project_memberships rows.

user_sub is TEXT (Authentik sub identifier) with NO FK to the users table. This
matches CONTEXT.md §Project membership model lock — Authentik is the sole user
store.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, TIMESTAMP, Text, text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


#: Sentinel project row id used for pre-Phase-10 data backfill.
#: All events/filter_presets/webhooks that existed before migration 009 point at
#: this project forever. Must match the literal in migration 009 byte-for-byte.
LEGACY_PROJECT_ID: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class EngagementType(str, enum.Enum):
    """Project engagement classification — matches engagement_type PG ENUM."""

    red_team = "red_team"
    tiber = "tiber"
    bbest = "bbest"
    internal = "internal"
    intel_only = "intel_only"


class ScopeType(str, enum.Enum):
    """Scope-row category — matches scope_type PG ENUM (7 values, locked order)."""

    keyword = "keyword"
    service = "service"
    domain = "domain"
    certificate = "certificate"
    whois = "whois"
    as_number = "as_number"
    ip_range = "ip_range"


class ProjectRole(str, enum.Enum):
    """Per-project role axis — orthogonal to global user role.

    Lead ≈ project-Admin, Contributor ≈ project-Analyst, Observer ≈ project-Viewer.
    """

    Lead = "Lead"
    Contributor = "Contributor"
    Observer = "Observer"


class Project(Base):
    """Project ORM — maps to projects table created in migration 009."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    engagement_type: Mapped[str] = mapped_column(
        PgEnum(
            "red_team", "tiber", "bbest", "internal", "intel_only",
            name="engagement_type", create_type=False,
        ),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Authentik sub, not FK — Authentik is sole user store per CONTEXT.md.
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )

    # EASM pre-columns (Phase 11 wires live; Phase 10 ships read-only)
    active_scans_authorised: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )
    scope_acknowledgement_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_auth_confirmed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
    )
    # Phase 11 / EASM-04: gate-audit column — records Authentik sub who confirmed auth
    active_auth_confirmed_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Phase 12 / BRP-04: GDPR per-project retention for person-type brand matches.
    # Migration 011 adds the column with server_default '90'.
    gdpr_person_match_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("90"), default=90,
    )

    # Phase 11 EASM relationship
    easm_scans = relationship(
        "EASMScan",
        cascade="all, delete-orphan",
        backref="project",
        lazy="dynamic",
    )

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"),
    )


class ProjectScopeRow(Base):
    """Individual scope entry for a project (keyword/domain/ip_range/…)."""

    __tablename__ = "project_scope_rows"

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
    scope_type: Mapped[str] = mapped_column(
        PgEnum(
            "keyword", "service", "domain", "certificate", "whois", "as_number", "ip_range",
            name="scope_type", create_type=False,
        ),
        nullable=False,
    )
    value: Mapped[str] = mapped_column(Text, nullable=False)
    contact: Mapped[str | None] = mapped_column(Text, nullable=True)
    exclude: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )
    # At least one of the two flags must be true (enforced via DB CHECK constraint
    # "project_scope_rows_at_least_one_flag" and Pydantic model_validator).
    active_test_scope: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
    )
    intel_scope: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"),
    )


class ProjectSource(Base):
    """Many-to-many binding between projects and sources (composite PK)."""

    __tablename__ = "project_sources"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"),
    )


class ProjectMembership(Base):
    """Per-project user role — user_sub is Authentik sub (no FK to users)."""

    __tablename__ = "project_memberships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_sub: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_role: Mapped[str] = mapped_column(
        PgEnum(
            "Lead", "Contributor", "Observer",
            name="project_role", create_type=False,
        ),
        nullable=False,
    )
    added_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"),
    )
