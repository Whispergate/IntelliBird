"""007 Pre-auth infrastructure hardening — credentials_key_version column + rekey canary row.

Revision ID: 007_credentials_key_version
Revises: 006_webhooks
Create Date: 2026-04-18

Phase 8 / INFRA-01, INFRA-03.

- ADD COLUMN sources.credentials_key_version INT NOT NULL DEFAULT 1
  PG 11+ fast-path: server_default='1' on a non-null column updates every
  existing row instantly via the column-default optimisation — no backfill
  needed. (See Postgres 11 release notes: "fast ALTER TABLE ... ADD COLUMN
  with a non-null default".)

- INSERT canary row id=00000000-0000-0000-0000-000000000000 name=_rekey_canary
  credentials_enc starts NULL. The FastAPI lifespan hook (Plan 08-03) seeds
  it with encrypt_credentials(settings.SECRET_KEY, {"canary": "intellibird-v1"})
  on first startup. Subsequent startups verify that decrypt round-trips under
  the current SECRET_KEY — fail means SECRET_KEY has rotated without rekey.

- ON CONFLICT (id) DO NOTHING guards re-running on an already-seeded DB.

Downgrade removes BOTH the canary row and the column.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_credentials_key_version"
down_revision: Union[str, None] = "006_webhooks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CANARY_ID: str = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    # 1. Add the key-version column. server_default="1" covers every existing row
    #    instantly thanks to PG 11+ non-null-default fast path — no row rewrite.
    op.add_column(
        "sources",
        sa.Column(
            "credentials_key_version",
            sa.Integer,
            nullable=False,
            server_default="1",
        ),
    )

    # 2. Insert the rekey canary row. credentials_enc seeded by lifespan hook
    #    on first backend startup (Plan 08-03).
    op.execute(
        """
        INSERT INTO sources (
            id, name, feed_type, url, enabled,
            poll_interval_sec, hot_retention_days,
            archive_policy, credentials_key_version,
            credentials_enc
        )
        VALUES (
            '00000000-0000-0000-0000-000000000000',
            '_rekey_canary', 'rss', 'https://canary.internal', false,
            3600, 30,
            'drop', 1,
            NULL
        )
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM sources WHERE id = '00000000-0000-0000-0000-000000000000'"
    )
    op.drop_column("sources", "credentials_key_version")
