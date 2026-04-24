"""PROD-05 load seed: asyncpg COPY of 50k events × 10 projects (500k rows default).

Fast, deterministic, memory-bounded seed for pgbench / events_query load tests.

Usage:
    import asyncpg
    conn = await asyncpg.connect(dsn)
    inserted = await seed_events(conn, project_ids=[...], n_per_project=50_000)

Key guarantees:
    - Deterministic: seeded RNG (random.Random(seed)) — same inputs yield same rows.
    - Memory-bounded: rows yielded in chunks of CHUNK_SIZE (10k) — does NOT
      materialise 500k rows at once.
    - Uses asyncpg.Connection.copy_records_to_table() → Postgres COPY FROM STDIN
      (orders of magnitude faster than ORM inserts).
    - Time distribution: exponential-recent-skew across last 90 days.

Columns populated (matches backend/app/models/events.py schema):
    id, project_id, observed_at, title, stix_type, content_hash, visibility,
    fetched_at, created_at, archived
"""
from __future__ import annotations

import hashlib
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterator

import asyncpg

CHUNK_SIZE: int = 10_000
SECONDS_PER_90_DAYS: int = 86_400 * 90

# Columns the COPY writes. Matches events table nullability after migration head.
EVENT_COLUMNS: list[str] = [
    "id",
    "stix_type",
    "project_id",
    "fetched_at",
    "observed_at",
    "title",
    "content_hash",
    "visibility",
    "archived",
    "created_at",
]


def _event_records(
    project_ids: list[uuid.UUID],
    n_per_project: int,
    rng: random.Random,
    now: datetime,
) -> Iterator[tuple]:
    """Yield event records one at a time — does NOT materialise the whole list.

    Timestamps recent-skew via exponential distribution with mean 30 days
    across a 90-day window. RNG is caller-supplied (deterministic).
    """
    for project_idx, pid in enumerate(project_ids):
        for i in range(n_per_project):
            # Mean ~30 days, clamped to 90 days for realism.
            offset_sec = min(rng.expovariate(1 / (86_400 * 30)), SECONDS_PER_90_DAYS)
            observed_at = now - timedelta(seconds=offset_sec)
            eid = uuid.uuid4()
            title = f"event-{project_idx}-{i}"
            ch = hashlib.sha256(f"{pid}:{i}:{project_idx}".encode()).hexdigest()
            yield (
                eid,              # id
                "observed-data",  # stix_type
                pid,              # project_id
                now,              # fetched_at
                observed_at,      # observed_at
                title,            # title
                ch,               # content_hash
                "shared",         # visibility
                False,            # archived
                now,              # created_at
            )


def _chunked(iterator: Iterator[tuple], size: int) -> Iterator[list[tuple]]:
    """Yield lists of up to `size` records from `iterator` — bounds peak memory."""
    chunk: list[tuple] = []
    for row in iterator:
        chunk.append(row)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


async def seed_events(
    conn: asyncpg.Connection,
    project_ids: list[uuid.UUID],
    n_per_project: int = 50_000,
    seed: int = 42,
) -> tuple[int, float]:
    """Bulk-insert n_per_project events per project via COPY. Returns (rows, elapsed_ms).

    Streaming: records are emitted in CHUNK_SIZE batches so peak RSS is bounded
    regardless of total row count. A single transaction wraps all chunks so
    either all rows land or none do.

    `project_ids`: caller-created project rows. Must already exist (FK).
    """
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)

    total = 0
    t0 = time.perf_counter()
    async with conn.transaction():
        records_iter = _event_records(project_ids, n_per_project, rng, now)
        for chunk in _chunked(records_iter, CHUNK_SIZE):
            await conn.copy_records_to_table(
                "events",
                records=chunk,
                columns=EVENT_COLUMNS,
            )
            total += len(chunk)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return total, elapsed_ms
