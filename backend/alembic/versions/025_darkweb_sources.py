"""025 - dark-web source types: tor_html, paste, telegram.

DARK-01..07.

Changes:
  1. Extend feed_type_enum with 'tor_html', 'paste', 'telegram'.
  2. Add sources.opsec_authorised BOOLEAN NOT NULL DEFAULT false.
  3. Add sources.session_enc TEXT NULL (Telethon StringSession, AES-256-GCM encrypted).
  4. Backfill confidence=0.4 for any existing dark-web rows (safe no-op on fresh DB).

NOTE: ALTER TYPE ... ADD VALUE must be committed before the new values can be
referenced in DML. We use op.get_context().autocommit_block() to emit the three
ADD VALUE statements outside the migration transaction so they are immediately
visible to the UPDATE backfill that follows.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "025_darkweb_sources"
down_revision = "024_enrichment_providers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Extend feed_type_enum outside the transaction so values are committed
    #    before the UPDATE backfill can reference them.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE feed_type_enum ADD VALUE IF NOT EXISTS 'tor_html'")
        op.execute("ALTER TYPE feed_type_enum ADD VALUE IF NOT EXISTS 'paste'")
        op.execute("ALTER TYPE feed_type_enum ADD VALUE IF NOT EXISTS 'telegram'")

    # 2. New columns on sources
    op.add_column(
        "sources",
        sa.Column(
            "opsec_authorised",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "sources",
        sa.Column("session_enc", sa.Text, nullable=True),
    )

    # 3. Confidence backfill for any pre-existing dark-web rows (idempotent no-op
    #    when no such rows exist - safe on fresh DB).
    op.execute(
        """
        UPDATE sources
        SET confidence = 0.4
        WHERE feed_type IN ('tor_html', 'paste', 'telegram')
          AND (confidence IS NULL OR confidence > 0.4)
        """
    )


def downgrade() -> None:
    # Drop the two new columns.
    # NOTE: PostgreSQL does not support DROP VALUE from an ENUM; the three new
    # feed_type_enum values are left in place on downgrade. This is safe - the
    # enum values are unused after downgrade and will be re-added as no-ops on
    # the next upgrade.
    op.drop_column("sources", "session_enc")
    op.drop_column("sources", "opsec_authorised")
