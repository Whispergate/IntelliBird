"""027 — taxii_clients table.

Phase 26 / TAXII-03, TAXII-04: Per-partner API key store for TAXII 2.1 outbound server.

Stores one row per external partner. The raw API key is NEVER stored — only its
SHA-256 hex digest (api_key_hash). TLP enforcement is at query time using tlp_max_level.

Design notes:
  * api_key_hash has a UNIQUE index — the lookup path for every inbound TAXII request.
  * revoked=true must be effective immediately — no caching in the service layer.
  * project_id FK CASCADE: deleting a project removes all partner keys for that project.
  * rate_limit_rpm stored here so the service layer reads it without a separate config lookup.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "027_taxii_clients"
down_revision: Union[str, None] = "026_actors_campaigns_audit"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "taxii_clients",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("api_key_hash", sa.Text(), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=False),
            nullable=False,
        ),
        sa.Column(
            "tlp_max_level",
            sa.Text(),
            server_default=sa.text("'green'"),
            nullable=False,
        ),
        sa.Column(
            "rate_limit_rpm",
            sa.Integer(),
            server_default=sa.text("60"),
            nullable=False,
        ),
        sa.Column(
            "revoked",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("api_key_hash", name="uq_taxii_clients_api_key_hash"),
    )
    op.create_index(
        "ix_taxii_clients_api_key_hash",
        "taxii_clients",
        ["api_key_hash"],
        unique=True,
    )
    op.create_index(
        "ix_taxii_clients_project_id",
        "taxii_clients",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_taxii_clients_project_id", table_name="taxii_clients")
    op.drop_index("ix_taxii_clients_api_key_hash", table_name="taxii_clients")
    op.drop_table("taxii_clients")
