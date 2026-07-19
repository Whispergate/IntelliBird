"""HTML-scrape source config - adds sources.scrape_config JSONB.

Revision ID: 017_html_scrape
Revises: 016_monitoring
Create Date: 2026-04-25

Quick task 260425-ovt: a "scraped feed" source type reuses the existing
``custom`` slot in ``feed_type_enum`` (created by migration 001) and stores
operator-supplied CSS selectors in a new sparse JSONB column. No ENUM change
required.

The column is nullable - existing rss/taxii/nvd rows are unaffected.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "017_html_scrape"
down_revision: Union[str, None] = "016_monitoring"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column(
            "scrape_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("sources", "scrape_config")
