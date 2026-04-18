"""M1 initial schema — sources, events hypertable, AGE, TLP seed, graph tables.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-04-17

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Enums FIRST — referenced by multiple tables below
    op.execute(
        "CREATE TYPE visibility_enum AS ENUM ('red_only','blue_only','shared')"
    )
    op.execute(
        "CREATE TYPE tag_source_enum AS ENUM ('feed_asserted','analyst','auto')"
    )
    op.execute(
        "CREATE TYPE feed_type_enum AS ENUM ('rss','taxii','nvd','custom')"
    )
    op.execute(
        "CREATE TYPE matrix_enum AS ENUM ('enterprise','ics','mobile')"
    )

    # 2. Extensions — idempotent
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")
    op.execute("CREATE EXTENSION IF NOT EXISTS age CASCADE")

    # 3. sources
    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("feed_type",
                  postgresql.ENUM("rss", "taxii", "nvd", "custom",
                                  name="feed_type_enum", create_type=False),
                  nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("credentials_enc", sa.Text(), nullable=True),
        sa.Column("poll_interval_sec", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("hot_retention_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_polled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_cursor", sa.Text(), nullable=True),
        sa.Column("last_status", sa.Text(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # 4. events (table, then convert to hypertable)
    # NOTE: TimescaleDB requires the partition column (observed_at) to be part
    # of any unique index / primary key. Composite PK (id, observed_at) satisfies
    # this and still gives uniqueness via the `id` UUID.
    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("stix_id", sa.Text(), nullable=True),
        sa.Column("stix_type", sa.Text(), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sources.id", ondelete="SET NULL"), nullable=True),
        sa.Column("fetched_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.text("now()")),
        sa.Column("raw_reference", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("tlp_marking_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("geo_lat", sa.Double(), nullable=True),
        sa.Column("geo_lon", sa.Double(), nullable=True),
        sa.Column("country_code", sa.String(2), nullable=True),
        sa.Column("visibility",
                  postgresql.ENUM("red_only", "blue_only", "shared",
                                  name="visibility_enum", create_type=False),
                  nullable=False, server_default="shared"),
        sa.Column("raw_stix", postgresql.JSONB(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", "observed_at", name="pk_events"),
    )
    op.execute(
        "SELECT create_hypertable('events', 'observed_at', chunk_time_interval => INTERVAL '7 days')"
    )

    # 5. attack_techniques
    op.create_table(
        "attack_techniques",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("technique_id", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("tactic", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("platform", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("matrix",
                  postgresql.ENUM("enterprise", "ics", "mobile",
                                  name="matrix_enum", create_type=False),
                  nullable=False),
        sa.Column("stix_id", sa.Text(), nullable=True),
        sa.Column("raw_stix", postgresql.JSONB(), nullable=True),
        sa.Column("fetched_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # 6. tlp_markings + canonical STIX 2.1 TLP 1.0 seed rows (PITFALLS H-4)
    op.create_table(
        "tlp_markings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("stix_definition_type", sa.Text(), nullable=False, server_default="tlp"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.execute(
        """
        INSERT INTO tlp_markings (id, name) VALUES
          ('613f2e26-407d-48c7-9eca-b8e91df99dc9', 'TLP:WHITE'),
          ('34098fce-860f-48ae-8e50-ebd3cc5e41da', 'TLP:GREEN'),
          ('f88d31f6-1208-47b8-8c13-1706eb6387bc', 'TLP:AMBER'),
          ('5e57c739-391a-4eb3-b6be-7d15ca92d5ed', 'TLP:RED')
        """
    )

    # 7. nodes, edges (relational graph — AGE deferred to M2)
    op.create_table(
        "nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("node_type", sa.Text(), nullable=False),
        sa.Column("stix_id", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("properties", postgresql.JSONB(), nullable=True),
        sa.Column("visibility",
                  postgresql.ENUM("red_only", "blue_only", "shared",
                                  name="visibility_enum", create_type=False),
                  nullable=False, server_default="shared"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_table(
        "edges",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("source_node_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_node_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relationship_type", sa.Text(), nullable=False),
        sa.Column("properties", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # 8. attack_technique_tags (SYS-02 provenance on every ATT&CK tag)
    op.create_table(
        "attack_technique_tags",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), primary_key=True),
        # NOTE: no FK to events.id — TimescaleDB hypertables can't be FK targets
        # (requires unique index including partition column). App enforces integrity.
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("technique_id", sa.Text(), nullable=False),
        sa.Column("tag_source",
                  postgresql.ENUM("feed_asserted", "analyst", "auto",
                                  name="tag_source_enum", create_type=False),
                  nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # 9. Indexes
    op.create_index("idx_events_source_id", "events", ["source_id"])
    op.create_index("idx_events_content_hash", "events", ["content_hash"])
    op.create_index("idx_events_visibility", "events", ["visibility"])
    op.create_index("idx_events_archived", "events", ["archived"])
    op.create_index("idx_events_raw_stix_gin", "events", ["raw_stix"], postgresql_using="gin")
    op.create_index("idx_attack_techniques_technique_id", "attack_techniques", ["technique_id"])
    op.create_index("idx_attack_techniques_matrix", "attack_techniques", ["matrix"])
    op.create_index("idx_nodes_node_type", "nodes", ["node_type"])
    op.create_index("idx_edges_source_node", "edges", ["source_node_id"])
    op.create_index("idx_edges_target_node", "edges", ["target_node_id"])
    op.create_index("idx_attack_tags_event_id", "attack_technique_tags", ["event_id"])


def downgrade() -> None:
    # Irreversible in M1 (PITFALLS M-7 mitigation = take a pg_dump before upgrade).
    # We still provide a best-effort downgrade for local dev resets.
    op.drop_table("attack_technique_tags")
    op.drop_table("edges")
    op.drop_table("nodes")
    op.drop_table("tlp_markings")
    op.drop_table("attack_techniques")
    op.drop_table("events")
    op.drop_table("sources")
    op.execute("DROP TYPE IF EXISTS matrix_enum")
    op.execute("DROP TYPE IF EXISTS feed_type_enum")
    op.execute("DROP TYPE IF EXISTS tag_source_enum")
    op.execute("DROP TYPE IF EXISTS visibility_enum")
    # Do not DROP EXTENSION timescaledb/age — they may be shared.
