"""Apache AGE spike — concurrent write/read smoke test under Dramatiq.

CONTEXT. Does NOT gate M1 — outcome recorded in AGE-SPIKE.md.
"""
from __future__ import annotations

import logging
import time

import dramatiq
from sqlalchemy import create_engine, text

from app.config import settings

logger = logging.getLogger(__name__)


def _sync_url() -> str:
    """Return a synchronous psycopg DSN derived from the async DATABASE_URL."""
    return settings.DATABASE_URL.replace("+asyncpg", "")


def _ensure_graph(conn, graph_name: str) -> None:
    """Create the AGE graph if it doesn't exist. Idempotent."""
    conn.execute(text("LOAD 'age'"))
    conn.execute(text("SET search_path = ag_catalog, '$user', public"))
    conn.execute(
        text(
            "SELECT create_graph(:name) "
            "WHERE NOT EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = :name)"
        ).bindparams(name=graph_name)
    )


def _drop_graph(conn, graph_name: str) -> None:
    conn.execute(text("LOAD 'age'"))
    conn.execute(text("SET search_path = ag_catalog, '$user', public"))
    conn.execute(
        text("SELECT drop_graph(:name, true) "
             "WHERE EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = :name)")
        .bindparams(name=graph_name)
    )


@dramatiq.actor(queue_name="maintenance", max_retries=0)
def age_spike_writer(graph_name: str, batch_id: str, count: int) -> None:
    """Insert `count` vertices tagged with `batch_id` into the AGE graph."""
    engine = create_engine(_sync_url(), future=True)
    with engine.begin() as conn:
        _ensure_graph(conn, graph_name)
        for i in range(count):
            cypher = (
                f"SELECT * FROM cypher('{graph_name}', $$ "
                f"CREATE (n:Spike {{batch:'{batch_id}', idx:{i}}}) RETURN n "
                f"$$) AS (n ag_catalog.agtype)"
            )
            conn.execute(text(cypher))
    engine.dispose()
    logger.info("age_spike_writer_done batch=%s count=%d", batch_id, count)


@dramatiq.actor(queue_name="maintenance", max_retries=0)
def age_spike_reader(graph_name: str, expect_at_least: int, timeout_sec: int = 30) -> int:
    """Poll the AGE graph until vertex count >= expect_at_least or timeout."""
    engine = create_engine(_sync_url(), future=True)
    observed = 0
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        with engine.connect() as conn:
            conn.execute(text("LOAD 'age'"))
            conn.execute(text("SET search_path = ag_catalog, '$user', public"))
            row = conn.execute(
                text(
                    f"SELECT count(*) FROM cypher('{graph_name}', $$ "
                    f"MATCH (n:Spike) RETURN n $$) AS (n ag_catalog.agtype)"
                )
            ).scalar_one()
            observed = int(row or 0)
            if observed >= expect_at_least:
                break
        time.sleep(0.5)
    engine.dispose()
    logger.info("age_spike_reader_done observed=%d expected>=%d", observed, expect_at_least)
    return observed
