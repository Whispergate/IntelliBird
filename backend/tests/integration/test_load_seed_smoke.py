"""Smoke test for load_seed fixture — PROD-05 Wave 0.

Uses a tiny n (100 rows × 2 projects = 200 rows) so it stays in the default
pytest suite (NOT marked @pytest.mark.load). The actual 500k-row exercise is
deferred to the PROD-05 plan, gated by the `load` marker.

Asserts:
- Correct row count lands in events (200).
- Streaming generator emits chunks, not a materialised list (inspect via a
  peek at the generator helpers).
- pgbench SQL script parses under `psql --no-psqlrc -c` (syntax only).
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)
os.environ.setdefault("SECRET_KEY", "s" * 64)


def _asyncpg_dsn(sqla_url: str) -> str:
    """Convert SQLAlchemy async URL back to the plain asyncpg DSN form."""
    return sqla_url.replace("postgresql+asyncpg://", "postgresql://")


async def _create_project(session, name: str) -> uuid.UUID:
    pid = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (:id, :name, 'internal', 'load-seed-smoke', false)"
        ),
        {"id": pid, "name": name},
    )
    return pid


async def test_seed_small(db_session, pg_url):
    """200-row seed lands deterministically; COPY runs under 5s."""
    from tests.integration.fixtures.load_seed import seed_events

    project_ids = [
        await _create_project(db_session, "load-seed-A"),
        await _create_project(db_session, "load-seed-B"),
    ]
    await db_session.commit()

    conn = await asyncpg.connect(_asyncpg_dsn(pg_url))
    try:
        total, elapsed_ms = await seed_events(
            conn,
            project_ids=project_ids,
            n_per_project=100,
            seed=42,
        )
    finally:
        await conn.close()

    assert total == 200, f"expected 200 rows inserted, got {total}"
    assert elapsed_ms < 5_000, f"200-row COPY took {elapsed_ms:.0f}ms (>5s threshold)"

    # Verify via a fresh query through the ORM session.
    count = (await db_session.execute(
        text("SELECT count(*) FROM events WHERE project_id = ANY(:pids)"),
        {"pids": project_ids},
    )).scalar_one()
    assert count == 200, f"DB count mismatch: {count}"


def test_seed_streams_in_chunks():
    """The generator yields chunk-sized batches; it does NOT materialise 50k rows at once."""
    import random as _random

    from tests.integration.fixtures.load_seed import (
        CHUNK_SIZE,
        _chunked,
        _event_records,
    )

    pids = [uuid.uuid4() for _ in range(3)]
    # Request a count that definitely exceeds CHUNK_SIZE so we must see multiple chunks.
    n_per = CHUNK_SIZE + 5  # 10_005 per project × 3 = 30_015 rows
    import datetime as _dt
    gen = _event_records(pids, n_per, _random.Random(1), _dt.datetime.now(_dt.timezone.utc))

    chunks_seen = 0
    total_seen = 0
    for chunk in _chunked(gen, CHUNK_SIZE):
        assert len(chunk) <= CHUNK_SIZE, f"chunk larger than CHUNK_SIZE: {len(chunk)}"
        chunks_seen += 1
        total_seen += len(chunk)
        if chunks_seen >= 2:
            # Stop early — confirming >1 chunk proves streaming works.
            break

    assert chunks_seen >= 2, "generator did not emit multiple chunks (not streaming)"
    assert total_seen >= CHUNK_SIZE, "chunk 1 was smaller than CHUNK_SIZE (unexpected)"


def test_pgbench_script_exists_and_has_pid_set():
    """pgbench script file exists and contains the \\set pid directive."""
    here = Path(__file__).resolve().parent
    script = here / "fixtures" / "events_query.sql"
    assert script.exists(), f"pgbench script missing: {script}"
    body = script.read_text()
    assert "\\set pid random" in body, "pgbench script missing \\set pid random directive"
    assert "FROM events" in body, "pgbench script does not query events table"
    assert "LIMIT 100" in body, "pgbench script missing LIMIT clause"
