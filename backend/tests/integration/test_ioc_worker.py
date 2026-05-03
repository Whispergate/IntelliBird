"""IOC-02 Dramatiq bulk_import_iocs actor integration tests — Plan 22-05 Task 2.

Covers:
  * `_async_bulk_import` writes rows + flips Redis status from running → complete
    with deterministic insert/update counts (no xmax / MERGE-side-effect counter).
  * `upsert_ioc_row` distinguishes insert vs update across two sequential calls.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _truncate_iocs(db_session):
    await db_session.execute(
        text("TRUNCATE TABLE ioc_event_links, iocs RESTART IDENTITY CASCADE")
    )
    await db_session.commit()
    yield


async def _seed_project(db_session, name: str) -> uuid.UUID:
    pid = uuid.uuid4()
    user_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (:id, :n, 'internal', :cb, false)"
        ),
        {"id": pid, "n": name, "cb": user_id},
    )
    await db_session.commit()
    return pid


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_bulk_import_iocs_actor_writes_rows_and_flips_status(db_session):
    """Stage a payload of 3 rows in Redis (one pre-existing → expect 1 update +
    2 inserts), invoke `_async_bulk_import` directly, and assert (a) the rows
    land in iocs, (b) Redis status flips to 'complete' with deterministic
    counters, (c) the payload key is deleted.
    """
    from app.services.iocs import normalise
    from app.services.redis_client import get_redis
    from app.workers.iocs import _async_bulk_import

    project_id = await _seed_project(db_session, "bulk-import-1")

    # Pre-seed one IOC so the second row in the payload triggers an update.
    pre_value = "10.0.0.1"
    pre_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    await db_session.execute(
        text(
            "INSERT INTO iocs "
            "(id, project_id, type, value, normalized_value, status, confidence, "
            " ttl_days, source, first_seen, last_seen, created_at, updated_at) "
            "VALUES (:id, :pid, 'ip', :v, :nv, 'active', 0.7, 30, 'manual', "
            ":ts, :ts, :ts, :ts)"
        ),
        {
            "id": pre_id, "pid": project_id, "v": pre_value,
            "nv": normalise("ip", pre_value), "ts": now,
        },
    )
    await db_session.commit()

    job_id = str(uuid.uuid4())
    payload_key = f"ioc:import:{job_id}"
    rows_payload = [
        {"type": "ip", "value": "10.0.0.2"},  # insert
        {"type": "ip", "value": "10.0.0.1"},  # update (matches pre-seeded)
        {"type": "domain", "value": "evil.example"},  # insert
    ]
    redis = await get_redis()
    await redis.set(payload_key, json.dumps(rows_payload), ex=600)

    user_sub = str(uuid.uuid4())
    result = await _async_bulk_import(
        job_id, payload_key, str(project_id), user_sub, "csv"
    )

    assert result["processed"] == 3
    assert result["inserted"] == 2
    assert result["updated"] == 1
    assert result["skipped"] == 0

    # IOC table now has 3 rows for this project (1 pre + 2 new).
    cnt = (await db_session.execute(
        text(
            "SELECT COUNT(*) FROM iocs WHERE project_id = :pid"
        ),
        {"pid": project_id},
    )).scalar_one()
    assert cnt == 3

    # Redis status flipped to 'complete'.
    status_blob = await redis.get(f"job:{job_id}:status")
    assert status_blob is not None
    status = json.loads(status_blob)
    assert status["status"] == "complete"
    assert status["inserted"] == 2 and status["updated"] == 1

    # Payload key cleaned up.
    assert (await redis.get(payload_key)) is None


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_upsert_ioc_row_distinguishes_insert_vs_update(db_session):
    """`upsert_ioc_row` returns 'inserted' on first call, 'updated' on second.

    No xmax inspection — the determination is made by an in-transaction SELECT
    against (project_id, type, normalized_value) before the upsert runs.
    """
    from app.schemas.iocs import IOCImportRow
    from app.services.iocs import upsert_ioc_row

    project_id = await _seed_project(db_session, "upsert-deterministic")
    row = IOCImportRow(type="ip", value="192.0.2.1")

    user_sub = str(uuid.uuid4())
    first = await upsert_ioc_row(
        db_session, row, project_id=project_id, source="csv", user_sub=user_sub
    )
    await db_session.commit()
    assert first == "inserted"

    second = await upsert_ioc_row(
        db_session, row, project_id=project_id, source="csv", user_sub=user_sub
    )
    await db_session.commit()
    assert second == "updated"
