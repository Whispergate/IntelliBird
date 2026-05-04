"""Extend destination_type_enum with email, pagerduty, opsgenie, ntfy — NOTIF-01.

Revision ID: a3f8b2c
Revises: 030_sigma_rules
Create Date: 2026-05-04

Adds four new notification channel types to the destination_type_enum so the
dispatcher can write and read email, pagerduty, opsgenie, and ntfy rows.

NOTE: ALTER TYPE ... ADD VALUE must be committed before the new values can be
referenced in DML. We use op.get_context().autocommit_block() to emit the four
ADD VALUE statements outside the migration transaction so they are immediately
visible (matches pattern in 025_darkweb_sources.py).
"""
from __future__ import annotations

from alembic import op

revision = "a3f8b2c"
down_revision = "030_sigma_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extend destination_type_enum outside the transaction so values are committed
    # immediately. ALTER TYPE ADD VALUE cannot run inside a transaction block.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE destination_type_enum ADD VALUE IF NOT EXISTS 'email'")
        op.execute("ALTER TYPE destination_type_enum ADD VALUE IF NOT EXISTS 'pagerduty'")
        op.execute("ALTER TYPE destination_type_enum ADD VALUE IF NOT EXISTS 'opsgenie'")
        op.execute("ALTER TYPE destination_type_enum ADD VALUE IF NOT EXISTS 'ntfy'")


def downgrade() -> None:
    # PostgreSQL cannot remove ENUM values — downgrade is a no-op.
    # To fully revert: recreate the type without these values and cast the column.
    pass
