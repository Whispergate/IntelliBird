"""AGE spike - concurrent write/read under two Dramatiq actors.

CONTEXT deliverable. Requires:
 - intellibird-db:m1 image running (db service)
 - redis service running
 - workers process running OR direct in-process call via.fn
"""
from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration

GRAPH_NAME = f"spike_{uuid.uuid4().hex[:8]}"


def _require_age(url: str) -> bool:
    """Skip the test if the connected DB does not have the AGE extension."""
    engine = create_engine(url, future=True)
    try:
        with engine.connect() as conn:
            exts = conn.execute(
                text("SELECT extname FROM pg_extension")
            ).scalars().all()
            return "age" in exts
    except Exception:
        return False
    finally:
        engine.dispose()


def test_age_concurrent_write_read(pg_container, monkeypatch) -> None:
    url = pg_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )
    if not _require_age(url.replace("+asyncpg", "")):
        pytest.skip(
            "AGE not present in test container. Run against intellibird-db:m1 "
            "to exercise the spike; base timescaledb image lacks AGE."
        )

    monkeypatch.setenv("SECRET_KEY", "a" * 64)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    import importlib
    import app.config as cfg
    importlib.reload(cfg)
    # Dramatiq actors can only be registered once per process - avoid re-registering
    # when the module has already been imported by earlier tests in the suite.
    import sys
    if "app.workers.age_spike" in sys.modules:
        import app.workers.age_spike as spike
    else:
        import app.workers.age_spike as spike  # noqa: F401 - first import registers actors

    batch_a = f"A-{uuid.uuid4().hex[:6]}"
    batch_b = f"B-{uuid.uuid4().hex[:6]}"

    # Pre-create the graph and the Spike vertex label so concurrent writers
    # don't race on create_graph / CREATE LABEL DDL.
    sync_pre_url = url.replace("+asyncpg", "")
    pre_engine = create_engine(sync_pre_url, future=True)
    with pre_engine.begin() as conn:
        spike._ensure_graph(conn, GRAPH_NAME)
        # Create one vertex + delete it to materialise the 'Spike' label table
        # ahead of the concurrent writers.
        conn.execute(text(
            f"SELECT * FROM cypher('{GRAPH_NAME}', $$ "
            f"CREATE (n:Spike {{batch:'warm', idx:-1}}) RETURN n "
            f"$$) AS (n ag_catalog.agtype)"
        ))
        conn.execute(text(
            f"SELECT * FROM cypher('{GRAPH_NAME}', $$ "
            f"MATCH (n:Spike {{batch:'warm'}}) DELETE n "
            f"$$) AS (n ag_catalog.agtype)"
        ))
    pre_engine.dispose()

    t1 = threading.Thread(target=spike.age_spike_writer.fn,
                          args=(GRAPH_NAME, batch_a, 10))
    t2 = threading.Thread(target=spike.age_spike_writer.fn,
                          args=(GRAPH_NAME, batch_b, 10))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    observed = spike.age_spike_reader.fn(GRAPH_NAME, expect_at_least=20, timeout_sec=10)
    assert observed >= 20, f"expected >=20 AGE vertices, saw {observed}"

    sync_url = url.replace("+asyncpg", "")
    engine = create_engine(sync_url, future=True)
    with engine.begin() as conn:
        spike._drop_graph(conn, GRAPH_NAME)
    engine.dispose()
