"""006 Webhook alerts tables - HOOK-01, HOOK-02.

Revision ID: 006_webhooks
Revises: 005_geo_backfill_and_indexes
Create Date: 2026-04-18

Creates destination_type_enum + webhooks + webhook_preset_bindings.

 correction vs 07-CONTEXT: auth_enc is TEXT (not bytea).
app.crypto.encrypt_credentials returns base64url str - matching
sources.credentials_enc pattern exactly.

: enum creation guarded via DO $$ EXCEPTION WHEN duplicate_object
block (established project pattern from migration 003) - handles
partial-migration re-run. Uses postgresql.ENUM(create_type=False) in
op.create_table - exact pattern from migration 001 (project standard).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006_webhooks"
down_revision: Union[str, None] = "005_geo_backfill_and_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    #: guarded enum creation - established project pattern from migration 003.
    # EXCEPTION WHEN duplicate_object THEN NULL handles partial-migration re-run.
    op.execute(
        "DO $$ BEGIN "
        "  CREATE TYPE destination_type_enum AS ENUM ('slack','teams','discord','generic'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )

    # Use postgresql.ENUM(create_type=False) - established project pattern from migration 001.
    # This suppresses the second CREATE TYPE that sa.Enum would otherwise emit.
    op.create_table(
        "webhooks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column(
            "destination_type",
            postgresql.ENUM(
                "slack", "teams", "discord", "generic",
                name="destination_type_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("url", sa.Text, nullable=False),
        #: Text (base64url) - NOT bytea.
        # app.crypto.encrypt_credentials returns a base64url string, matching
        # the sources.credentials_enc pattern exactly.
        sa.Column("auth_enc", sa.Text, nullable=True),
        sa.Column(
            "batching_window_sec",
            sa.Integer,
            nullable=False,
            server_default="300",
        ),
        sa.Column(
            "enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("last_dispatch_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_delivery_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_delivery_status", sa.Text, nullable=True),
        sa.Column(
            "consecutive_failures",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "webhook_preset_bindings",
        sa.Column(
            "webhook_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("webhooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "preset_name",
            sa.Text,
            sa.ForeignKey("filter_presets.name", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("webhook_id", "preset_name"),
    )


def downgrade() -> None:
    op.drop_table("webhook_preset_bindings")
    op.drop_table("webhooks")
    op.execute("DROP TYPE IF EXISTS destination_type_enum")
