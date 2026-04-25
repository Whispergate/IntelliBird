"""PROD-05 load test: 50k events × 10 projects, EXPLAIN Index Scan + p95 < 200ms.

Gated by `@pytest.mark.load` — excluded from the default suite (`-m 'not load'`
in backend/pyproject.toml [tool.pytest.ini_options] addopts). Run via
`scripts/run-load-test.sh` or `uv run pytest -m load
tests/integration/test_prod05_events_query_load.py -s`.

Measured query:
    SELECT id, observed_at, title
      FROM events
      WHERE project_id = $1
      ORDER BY observed_at DESC
      LIMIT 100;

This is the keyset-cursor shape used by the non-FTS path in
backend/app/routers/events.py (see `events_query` keyset cursor on
(observed_at, id); the first-page form is the LIMIT 100 variant above).

Assertions (both must hold to turn the p95 assertion into a regression fence):
  1. Every measured EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) root plan walks
     down to an Index Scan / Index Only Scan on `events_project_observed_idx`
     (confirmed name from alembic 009_projects_and_memberships.py L344). If a
     future migration drops or renames the index, this flips red before the
     latency threshold does.
  2. sorted(times_ms)[int(0.95 * 200)] < 200 after 10-run cache warm-up
     (Pitfall 5: cold buffers skew first samples into the ~800ms range).

Emits a fenced markdown "Evidence Block" to stdout at the end of the run; the
operator copy-pastes this into docs/ops/load-test-results.md.
"""
from __future__ import annotations

import getpass
import json
import os
import statistics
import time
import uuid
from datetime import datetime, timezone

import asyncpg
import pytest
from sqlalchemy import text

pytestmark = [pytest.mark.load, pytest.mark.integration]


# Confirmed against backend/alembic/versions/009_projects_and_memberships.py L344:
#     CREATE INDEX events_project_observed_idx ON events (project_id, observed_at DESC);
EXPECTED_INDEX_NAME = "events_project_observed_idx"

# Plan 13-05: 50k per project × 10 projects = 500k rows.
N_PROJECTS = 10
N_PER_PROJECT = 50_000

# Warm-up before measurement (Pitfall 5) + measurement sample count.
WARMUP_ITERATIONS = 10
SAMPLE_ITERATIONS = 200

# Threshold in ms — PROD-05 success criterion from REQUIREMENTS.md.
P95_THRESHOLD_MS = 200.0

# The measured query. Matches the first-page, no-FTS shape in
# backend/app/routers/events.py (keyset cursor on (observed_at, id)).
MEASURED_QUERY = (
    "SELECT id, observed_at, title "
    "FROM events "
    "WHERE project_id = $1 "
    "ORDER BY observed_at DESC "
    "LIMIT 100"
)


os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)
os.environ.setdefault("SECRET_KEY", "s" * 64)


def _asyncpg_dsn(sqla_url: str) -> str:
    """Convert SQLAlchemy async URL → plain asyncpg DSN."""
    return sqla_url.replace("postgresql+asyncpg://", "postgresql://")


async def _create_project(session, name: str) -> uuid.UUID:
    pid = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (:id, :name, 'internal', 'prod05-load', false)"
        ),
        {"id": pid, "name": name},
    )
    return pid


def _walk(node: dict):
    """Depth-first walk of EXPLAIN JSON plan tree (Pattern 4)."""
    yield node
    for child in node.get("Plans", []) or []:
        yield from _walk(child)


def _find_index_scan(plan: dict, expected_index: str) -> dict | None:
    """Return the first Index Scan / Index Only Scan node on expected_index,
    or None. Tolerates the Index Scan being a child of Limit/Sort (common
    shape for ORDER BY observed_at DESC LIMIT 100). On TimescaleDB hypertables
    the Custom Scan (ChunkAppend) wraps per-chunk Index Scans whose names
    follow `_hyper_<N>_<M>_chunk_<base_index>` — match either the literal
    base name or any chunk-suffixed variant ending in it."""
    for node in _walk(plan):
        if node.get("Node Type") not in ("Index Scan", "Index Only Scan"):
            continue
        idx_name = node.get("Index Name", "")
        if idx_name == expected_index or idx_name.endswith("_" + expected_index):
            return node
    return None


@pytest.mark.asyncio
async def test_prod05_events_query_load(db_session, pg_url, capsys):
    """PROD-05 regression fence: Index Scan + p95 < 200ms @ 500k rows."""
    # --- Arrange: 10 projects + 50k events each via COPY ---
    from tests.integration.fixtures.load_seed import seed_events

    project_ids: list[uuid.UUID] = []
    for i in range(N_PROJECTS):
        project_ids.append(await _create_project(db_session, f"prod05-p{i}"))
    await db_session.commit()

    dsn = _asyncpg_dsn(pg_url)
    conn = await asyncpg.connect(dsn)
    try:
        seed_start = time.perf_counter()
        total, seed_elapsed_ms = await seed_events(
            conn,
            project_ids=project_ids,
            n_per_project=N_PER_PROJECT,
            seed=42,
        )
        assert total == N_PROJECTS * N_PER_PROJECT, (
            f"expected {N_PROJECTS * N_PER_PROJECT} rows, got {total}"
        )

        # ANALYZE so the planner has fresh stats for the composite index.
        await conn.execute("ANALYZE events")

        # --- Warm the buffer cache (Pitfall 5) ---
        import random as _r
        rng = _r.Random(1337)
        for _ in range(WARMUP_ITERATIONS):
            pid = rng.choice(project_ids)
            await conn.fetch(MEASURED_QUERY, pid)

        # --- Measure: N=200 EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ---
        times_ms: list[float] = []
        first_sample: dict | None = None
        last_sample: dict | None = None
        explain_sql = (
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + MEASURED_QUERY
        )
        for i in range(SAMPLE_ITERATIONS):
            pid = rng.choice(project_ids)
            rows = await conn.fetch(explain_sql, pid)
            # asyncpg returns the JSON already decoded for the QUERY PLAN column.
            raw = rows[0][0]
            doc = json.loads(raw) if isinstance(raw, str) else raw
            plan = doc[0]["Plan"]

            idx_node = _find_index_scan(plan, EXPECTED_INDEX_NAME)
            assert idx_node is not None, (
                f"sample #{i}: expected Index Scan on {EXPECTED_INDEX_NAME}; "
                f"got node types: {[n.get('Node Type') for n in _walk(plan)]}"
            )

            times_ms.append(float(plan["Actual Total Time"]))
            if first_sample is None:
                first_sample = doc
            last_sample = doc

    finally:
        await conn.close()

    # --- Assert: p95 < 200ms ---
    sorted_times = sorted(times_ms)
    p95_idx = int(0.95 * SAMPLE_ITERATIONS)
    p95 = sorted_times[p95_idx]
    p50 = statistics.median(sorted_times)
    p99_idx = min(int(0.99 * SAMPLE_ITERATIONS), SAMPLE_ITERATIONS - 1)
    p99 = sorted_times[p99_idx]

    # --- Evidence block (operator pastes into docs/ops/load-test-results.md) ---
    operator = os.environ.get("USER") or getpass.getuser() or "unknown"
    now = datetime.now(timezone.utc).isoformat()
    block = (
        "\n\n"
        "```markdown\n"
        f"### PROD-05 evidence — {now}\n"
        f"- Operator: {operator}\n"
        f"- Seed: {total} rows ({N_PROJECTS} projects × {N_PER_PROJECT})"
        f" in {seed_elapsed_ms:.0f} ms\n"
        f"- Warm-up: {WARMUP_ITERATIONS} iterations (discarded)\n"
        f"- Sample: {SAMPLE_ITERATIONS} iterations\n"
        f"- Index asserted: {EXPECTED_INDEX_NAME}\n"
        f"- p50: {p50:.2f} ms\n"
        f"- p95: {p95:.2f} ms (threshold {P95_THRESHOLD_MS} ms)\n"
        f"- p99: {p99:.2f} ms\n"
        f"- min: {min(sorted_times):.2f} ms\n"
        f"- max: {max(sorted_times):.2f} ms\n"
        "\n"
        "First sample EXPLAIN JSON:\n"
        "```json\n"
        f"{json.dumps(first_sample, indent=2, default=str)}\n"
        "```\n"
        "\n"
        "Last sample EXPLAIN JSON:\n"
        "```json\n"
        f"{json.dumps(last_sample, indent=2, default=str)}\n"
        "```\n"
        "```\n"
    )
    # Use capsys-safe print — visible with `pytest -s`.
    print(block)

    assert p95 < P95_THRESHOLD_MS, (
        f"p95 {p95:.2f}ms >= {P95_THRESHOLD_MS}ms "
        f"(p50={p50:.2f}ms, p99={p99:.2f}ms, n={SAMPLE_ITERATIONS})"
    )
