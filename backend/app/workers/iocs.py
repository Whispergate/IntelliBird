"""IOC Dramatiq actors — Phase 22.

Section 1 (Plan 22-04): backfill_iocs_actor — async backfill driven by
  POST /api/admin/iocs/backfill so the HTTP request returns 202 + job_id
  and the long-running scan over ~29k events runs off-thread.

Section 2 (Plan 22-05): bulk_import_iocs — appended in a later wave.

Per-loop async engine pattern (verbatim from `app/workers/ai.py:48`):
each Dramatiq invocation gets a fresh engine bound to the current loop;
re-using a module-global engine across worker threads breaks asyncio
("Future attached to a different loop"). See workers/ai.py for the
canonical reference implementation.

Job status protocol (Redis):
  job:{job_id}:status — JSON {status: queued|running|complete|failed,
                              processed, inserted, error?} TTL=3600s
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid as _uuid

import dramatiq

from app.workers.ai import _make_engine_and_session  # reuse per-loop pattern

logger = logging.getLogger(__name__)


# ===== Section 1: backfill (Plan 22-04) =====


async def _async_backfill(job_id: str, project_id: str | None) -> dict[str, int]:
    """Async body of `backfill_iocs_actor`.

    Exposed as a separate top-level coroutine so tests (running inside
    pytest-asyncio's loop) can drive the backfill without re-entering
    `asyncio.run`. The Dramatiq decorator below wraps this in a fresh
    event loop per worker invocation.
    """
    from app.services.iocs import backfill_iocs_for_project  # noqa: PLC0415
    from app.services.redis_client import get_redis  # noqa: PLC0415

    engine, session_factory = _make_engine_and_session()
    redis = None
    try:
        redis = await get_redis()
        await redis.set(
            f"job:{job_id}:status",
            json.dumps({"status": "running", "processed": 0, "inserted": 0}),
            ex=3600,
        )
        pid = _uuid.UUID(project_id) if project_id else None
        async with session_factory() as session:
            result = await backfill_iocs_for_project(session, project_id=pid)
        await redis.set(
            f"job:{job_id}:status",
            json.dumps({"status": "complete", **result}),
            ex=3600,
        )
        logger.info(
            "backfill_iocs_actor_complete job_id=%s project_id=%s result=%s",
            job_id, project_id, result,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "backfill_iocs_actor_failed job_id=%s project_id=%s error=%r",
            job_id, project_id, exc,
        )
        try:
            if redis is not None:
                await redis.set(
                    f"job:{job_id}:status",
                    json.dumps({"status": "failed", "error": str(exc)[:500]}),
                    ex=3600,
                )
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        await engine.dispose()


@dramatiq.actor(
    queue_name="ingest",
    max_retries=2,
    min_backoff=10_000,
    max_backoff=300_000,
)
def backfill_iocs_actor(job_id: str, project_id: str | None) -> None:
    """Async backfill admin endpoint (RESEARCH Pitfall 6).

    Args:
        job_id: caller-generated UUID; UI polls `job:{job_id}:status`.
        project_id: optional UUID string; None = all projects (admin global run).
    """
    asyncio.run(_async_backfill(job_id, project_id))


# ===== Section 2: bulk_import (Plan 22-05) =====


async def _async_bulk_import(
    job_id: str,
    payload_key: str,
    project_id: str | None,
    user_sub: str,
    source: str,
) -> dict[str, int]:
    """Async body of `bulk_import_iocs`.

    Extracted as a top-level coroutine so integration tests under pytest-asyncio
    can drive it directly without re-entering `asyncio.run` (mirrors
    `_async_backfill` from Section 1).

    Reads `payload_key` from Redis (a JSON-serialised list of IOCImportRow
    dicts), upserts each row via `upsert_ioc_row` with deterministic
    insert/update counting, and writes progress to ``job:{job_id}:status``.
    """
    from app.schemas.iocs import IOCImportRow  # noqa: PLC0415
    from app.services.iocs import upsert_ioc_row  # noqa: PLC0415
    from app.services.redis_client import get_redis  # noqa: PLC0415

    engine, session_factory = _make_engine_and_session()
    redis = None
    try:
        redis = await get_redis()
        raw = await redis.get(payload_key)
        if not raw:
            await redis.set(
                f"job:{job_id}:status",
                json.dumps({"status": "failed", "error": "payload_missing"}),
                ex=3600,
            )
            return {"status": "failed"}
        rows_json = json.loads(raw)
        rows = [IOCImportRow(**d) for d in rows_json]
        total = len(rows)

        await redis.set(
            f"job:{job_id}:status",
            json.dumps({"status": "running", "processed": 0, "total": total}),
            ex=3600,
        )

        pid = _uuid.UUID(project_id) if project_id else None
        processed = inserted = updated = skipped = 0
        async with session_factory() as session:
            for i, row in enumerate(rows, start=1):
                try:
                    outcome = await upsert_ioc_row(
                        session, row,
                        project_id=pid, source=source, user_sub=user_sub,
                    )
                    if outcome == "inserted":
                        inserted += 1
                    elif outcome == "updated":
                        updated += 1
                    else:
                        skipped += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "ioc_import_row_failed line=%s error=%r",
                        getattr(row, "line", None), exc,
                    )
                    skipped += 1
                processed = i
                if processed % 500 == 0:
                    await session.commit()
                    await redis.set(
                        f"job:{job_id}:status",
                        json.dumps({
                            "status": "running",
                            "processed": processed, "total": total,
                            "inserted": inserted, "updated": updated, "skipped": skipped,
                        }),
                        ex=3600,
                    )
            await session.commit()

        result = {
            "processed": processed, "total": total,
            "inserted": inserted, "updated": updated, "skipped": skipped,
        }
        await redis.set(
            f"job:{job_id}:status",
            json.dumps({"status": "complete", **result}),
            ex=3600,
        )
        try:
            await redis.delete(payload_key)
        except Exception:  # noqa: BLE001
            pass
        logger.info(
            "bulk_import_iocs_complete job_id=%s result=%s", job_id, result,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("bulk_import_iocs_failed job_id=%s", job_id)
        try:
            if redis is not None:
                await redis.set(
                    f"job:{job_id}:status",
                    json.dumps({"status": "failed", "error": str(exc)[:500]}),
                    ex=3600,
                )
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        await engine.dispose()


@dramatiq.actor(
    queue_name="ingest",
    max_retries=2,
    min_backoff=10_000,
    max_backoff=60_000,
)
def bulk_import_iocs(
    job_id: str,
    payload_key: str,
    project_id: str | None,
    user_sub: str,
    source: str,
) -> None:
    """Process a parsed bulk-import payload from Redis and upsert IOC rows.

    Args:
        job_id: caller-generated UUID; UI polls `job:{job_id}:status`.
        payload_key: Redis key holding the JSON-serialised IOCImportRow list.
        project_id: optional UUID string; None = global rows (Admin uploads).
        user_sub: caller's user.id (recorded as iocs.created_by on insert).
        source: import format used as iocs.source ('csv' | 'json' | 'stix').
    """
    asyncio.run(
        _async_bulk_import(job_id, payload_key, project_id, user_sub, source)
    )


__all__ = [
    "backfill_iocs_actor",
    "_async_backfill",
    "bulk_import_iocs",
    "_async_bulk_import",
]
