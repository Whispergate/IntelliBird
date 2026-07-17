"""024 — enrichment_providers + ioc_enrichments tables.

ENRICH-01, ENRICH-04.

enrichment_providers: per-project (or global, project_id NULL) API key config
  for reputation providers. UNIQUE (project_id, provider) NULLS NOT DISTINCT.

ioc_enrichments: one row per (ioc_id, provider) storing raw API response +
  normalised verdict. UNIQUE (ioc_id, provider) — upserted on re-enrichment.

ioc_verdict ENUM: clean | suspicious | malicious | unknown.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg


revision = "024_enrichment_providers"
down_revision = "019_iocs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create ioc_verdict ENUM
    op.execute(
        "CREATE TYPE ioc_verdict AS ENUM ('clean', 'suspicious', 'malicious', 'unknown')"
    )

    # 2. enrichment_providers
    op.create_table(
        "enrichment_providers",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("credentials_enc", sa.Text, nullable=True),
        sa.Column(
            "credentials_key_version",
            sa.Integer,
            nullable=False,
            server_default="1",
        ),
        sa.Column("daily_request_cap", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "uq_enrichment_providers_project_provider",
        "enrichment_providers",
        ["project_id", "provider"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )

    # 3. ioc_enrichments
    op.create_table(
        "ioc_enrichments",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "ioc_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("iocs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("raw_response_jsonb", pg.JSONB, nullable=True),
        sa.Column(
            "verdict",
            pg.ENUM(
                "clean",
                "suspicious",
                "malicious",
                "unknown",
                name="ioc_verdict",
                create_type=False,
            ),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("score", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "fetched_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("evidence_text", sa.Text, nullable=True),
    )
    op.create_index(
        "uq_ioc_enrichments_ioc_provider",
        "ioc_enrichments",
        ["ioc_id", "provider"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("ioc_enrichments")
    op.drop_index("uq_enrichment_providers_project_provider", table_name="enrichment_providers")
    op.drop_table("enrichment_providers")
    op.execute("DROP TYPE IF EXISTS ioc_verdict")
