"""User ORM — AUTH-01, AUTH-02, AUTH-03.

Single table for local + OIDC accounts. Columns match migration 008_users_and_auth.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Enum, Integer, TIMESTAMP, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    username: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)  # NULL for OIDC-only users
    oidc_sub: Mapped[str | None] = mapped_column(Text, nullable=True)  # NULL for local users; partial UNIQUE index when set
    role: Mapped[str] = mapped_column(
        Enum("Admin", "Analyst", "Viewer", name="user_role", create_type=False),
        nullable=False,
    )
    # Orthogonal axis: subset of {'red', 'blue'}. Admins always get both (enforced at creation).
    dashboard_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Bulk session invalidation: incrementing this column fails every outstanding
    # JWT whose token_version claim < current DB value (AuthMiddleware check).
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True,
    )
