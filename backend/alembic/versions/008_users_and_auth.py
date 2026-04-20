"""users_and_auth

Revision ID: 008_users_and_auth
Revises: 007_credentials_key_version
Create Date: 2026-04-18

Phase 9 / AUTH-01, AUTH-02, AUTH-03.

Creates the users table (local + OIDC accounts in a single table per CONTEXT.md):
  - password_hash NULL for OIDC-only users
  - oidc_sub NULL for local users, UNIQUE when present
  - role ENUM (Admin/Analyst/Viewer)
  - dashboard_roles TEXT[] orthogonal axis ({'red','blue'} subset)
  - token_version INT for bulk session invalidation on password reset
  - must_change_password BOOL for admin-temp-password -> forced-reset flow

Enum creation uses raw DO-block (CREATE TYPE IF NOT EXISTS does not exist in PostgreSQL;
DO $$ ... EXCEPTION WHEN duplicate_object ... $$ is the idempotent pattern — established
in migration 003 per STATE.md).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "008_users_and_auth"
down_revision = "007_credentials_key_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent enum creation (pattern from migration 003)
    op.execute(
        """
        DO $$
        BEGIN
            CREATE TYPE user_role AS ENUM ('Admin', 'Analyst', 'Viewer');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("oidc_sub", sa.Text(), nullable=True),
        sa.Column(
            "role",
            postgresql.ENUM(
                "Admin", "Analyst", "Viewer",
                name="user_role", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "dashboard_roles",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "token_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_login_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )

    op.create_index("uq_users_username", "users", ["username"], unique=True)
    op.create_index(
        "uq_users_oidc_sub", "users", ["oidc_sub"], unique=True,
        postgresql_where=sa.text("oidc_sub IS NOT NULL"),
    )
    op.create_index(
        "ix_users_enabled", "users", ["enabled"],
        postgresql_where=sa.text("enabled = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_enabled", table_name="users")
    op.drop_index("uq_users_oidc_sub", table_name="users")
    op.drop_index("uq_users_username", table_name="users")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS user_role")
