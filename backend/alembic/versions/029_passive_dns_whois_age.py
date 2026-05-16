"""029 — passive_dns_records, whois_cache, AGE graph labels for Phase 28.

Phase 28 / ENRICH-06, ENRICH-07, ENRICH-08, GRAPH-01.

passive_dns_records: per-IOC passive DNS lookup results from external providers
  (SecurityTrails, Mnemonic, RiskIQ Community). Linked to iocs via FK ON DELETE
  CASCADE so records are automatically pruned when an IOC is removed.

whois_cache: domain → WHOIS data cache with TTL gating via fetched_at.
  UNIQUE on domain ensures a single cache row per domain; callers upsert by domain.

AGE graph additions:
  * Idempotently creates intellibird_graph if not already present.
  * Creates DomainPivot vertex label for pivot-node enrichment graph nodes.
  * Creates SHARES_INFRA edge label for IP-sharing multi-hop connections.

Note: enrichment_providers.provider is plain TEXT with no CHECK constraint
(see 024_enrichment_providers.py) — no constraint modification needed for
the three new passive-DNS providers; they are accepted without schema change.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "029_passive_dns_whois_age"
down_revision: Union[str, None] = "028_sandbox_yara"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. passive_dns_records
    # ------------------------------------------------------------------
    op.create_table(
        "passive_dns_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "ioc_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("iocs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ip", sa.Text(), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_passive_dns_ioc_id",
        "passive_dns_records",
        ["ioc_id"],
    )

    # ------------------------------------------------------------------
    # 2. whois_cache
    # ------------------------------------------------------------------
    op.create_table(
        "whois_cache",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("domain", sa.Text(), nullable=False, unique=True),
        sa.Column("raw_json", postgresql.JSONB(), nullable=True),
        sa.Column("registrar", sa.Text(), nullable=True),
        sa.Column("registrant_email", sa.Text(), nullable=True),
        sa.Column("registration_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("nameservers", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_whois_cache_domain",
        "whois_cache",
        ["domain"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # 3. AGE graph — idempotent intellibird_graph + labels
    #
    # AGE DDL must run through the raw synchronous connection so that
    # LOAD 'age' takes effect for the whole session.  op.get_bind()
    # returns the underlying psycopg2-based connection during Alembic
    # batch migrations.
    # ------------------------------------------------------------------
    conn = op.get_bind()
    conn.execute(sa.text("LOAD 'age'"))
    conn.execute(sa.text("SET search_path = ag_catalog, \"$user\", public"))

    # Create graph only when it does not already exist
    result = conn.execute(
        sa.text("SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'intellibird_graph'")
    )
    if result.first() is None:
        conn.execute(
            sa.text("SELECT * FROM ag_catalog.create_graph('intellibird_graph')")
        )

    # CREATE VLABEL/ELABEL are AGE SQL-level DDL, not Cypher — call via
    # ag_catalog.create_vlabel / create_elabel SQL functions.
    # Gate on ag_catalog.ag_label to stay idempotent.
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM ag_catalog.ag_label"
            " JOIN ag_catalog.ag_graph ON ag_label.graph = ag_graph.graphid"
            " WHERE ag_graph.name = 'intellibird_graph' AND ag_label.name = 'DomainPivot'"
        )
    ).first()
    if row is None:
        conn.execute(
            sa.text("SELECT ag_catalog.create_vlabel('intellibird_graph', 'DomainPivot')")
        )

    row = conn.execute(
        sa.text(
            "SELECT 1 FROM ag_catalog.ag_label"
            " JOIN ag_catalog.ag_graph ON ag_label.graph = ag_graph.graphid"
            " WHERE ag_graph.name = 'intellibird_graph' AND ag_label.name = 'SHARES_INFRA'"
        )
    ).first()
    if row is None:
        conn.execute(
            sa.text("SELECT ag_catalog.create_elabel('intellibird_graph', 'SHARES_INFRA')")
        )


def downgrade() -> None:
    # Drop AGE labels first (before tables, in case any graph nodes reference them)
    conn = op.get_bind()
    conn.execute(sa.text("LOAD 'age'"))
    conn.execute(sa.text("SET search_path = ag_catalog, \"$user\", public"))
    # DROP VLABEL/ELABEL are AGE SQL DDL — use drop_label SQL function.
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM ag_catalog.ag_label"
            " JOIN ag_catalog.ag_graph ON ag_label.graph = ag_graph.graphid"
            " WHERE ag_graph.name = 'intellibird_graph' AND ag_label.name = 'SHARES_INFRA'"
        )
    ).first()
    if row is not None:
        conn.execute(
            sa.text("SELECT ag_catalog.drop_label('intellibird_graph', 'SHARES_INFRA')")
        )

    row = conn.execute(
        sa.text(
            "SELECT 1 FROM ag_catalog.ag_label"
            " JOIN ag_catalog.ag_graph ON ag_label.graph = ag_graph.graphid"
            " WHERE ag_graph.name = 'intellibird_graph' AND ag_label.name = 'DomainPivot'"
        )
    ).first()
    if row is not None:
        conn.execute(
            sa.text("SELECT ag_catalog.drop_label('intellibird_graph', 'DomainPivot')")
        )

    # Drop tables in reverse dependency order
    op.drop_index("ix_whois_cache_domain", table_name="whois_cache")
    op.drop_table("whois_cache")
    op.drop_index("ix_passive_dns_ioc_id", table_name="passive_dns_records")
    op.drop_table("passive_dns_records")
