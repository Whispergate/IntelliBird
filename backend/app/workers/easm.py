"""EASM Dramatiq actor on queue='easm'.

Orchestrates:
1. Semaphore acquire (raise Retry if over cap)
2. Scope derivation (plan 11-02)
3. Safelist validation (defence-in-depth; router already validated)
4. docker run -d BBOT (plan 11-04a bbot_runner.launch_bbot_scan)
5. Stream docker logs --follow (bbot_runner.stream_bbot_logs)
6. For each event: persist_finding + should_promote -> promote_finding_to_event + INSERT Event
7. Update easm_scans.status=finished (or failed/cancelled)
8. Semaphore release (always, in finally)

Cancellation: TimeLimitExceeded caught; cancel_bbot_container(container_id); status='cancelled'.

Time limits: the actor decorator sets a default based on the passive cap. The launch_scan
router (plan 11-05) overrides per-mode via `.send_with_options(time_limit=<ms>)` — passive
gets BBOT_PASSIVE_MAX_SECONDS, active gets BBOT_ACTIVE_MAX_SECONDS (I1 from checker feedback).
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import uuid

import dramatiq
import redis as redis_lib
from dramatiq.middleware import TimeLimitExceeded
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models.easm import EASMFinding, EASMScan
from app.models.events import Event
from app.services import bbot_runner, bbot_safelist, easm_promoter, easm_scope

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dramatiq actor
# ---------------------------------------------------------------------------


@dramatiq.actor(
    queue_name="easm",
    max_retries=0,  # retry handled via explicit dramatiq.Retry in semaphore block
    time_limit=int(settings.BBOT_PASSIVE_MAX_SECONDS * 1000 * 1.1),  # default = passive + 10% grace
    # Per-mode override is applied by the router via
    # run_bbot_scan.send_with_options(args=[str(scan.id)], time_limit=<ms>) (I1).
)
def run_bbot_scan(scan_id: str) -> None:
    """Entry point. scan_id is a string UUID (Dramatiq serialisation).

    Each invocation runs in its own asyncio event loop. We create a
    per-invocation async engine + session factory inside the inner coroutine
    so the asyncpg connection pool binds to THIS loop, not the loop of a
    prior invocation. Reusing the module-global engine from app.database
    leaks loop affinity across actor calls and raises
    'Future attached to a different loop' on the second run.
    """
    asyncio.run(_run_bbot_scan_inner(uuid.UUID(scan_id)))


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


async def _run_bbot_scan_inner(scan_id: uuid.UUID) -> None:
    r = redis_lib.from_url(settings.REDIS_URL)
    limit = settings.BBOT_CONCURRENT_LIMIT

    if not bbot_runner.acquire_semaphore(r, limit):
        log.info("bbot_concurrent_cap_exceeded scan_id=%s limit=%s", scan_id, limit)
        raise dramatiq.Retry(delay=30_000)

    # Per-invocation engine + session factory bound to THIS loop.
    # Disposed in the outer finally; never shared across actor invocations.
    local_engine = create_async_engine(
        settings.DATABASE_URL, pool_pre_ping=True, future=True, pool_size=2, max_overflow=2,
    )
    async_session_factory = async_sessionmaker(
        local_engine, expire_on_commit=False, class_=AsyncSession,
    )

    container_id: str | None = None
    try:
        async with async_session_factory() as db:
            scan = (await db.execute(select(EASMScan).where(EASMScan.id == scan_id))).scalar_one()
            targets = await easm_scope.derive_bbot_seeds(db, scan.project_id)
            blacklist = await easm_scope.derive_bbot_blacklist(db, scan.project_id)

            # Defence-in-depth: revalidate modules (router already validated)
            ok, invalid = bbot_safelist.validate_modules(list(scan.modules))
            if not ok:
                await _mark_scan_failed(db, scan_id, f"invalid_modules: {invalid}")
                return
            if not targets:
                await _mark_scan_failed(db, scan_id, "empty_active_test_scope")
                return

            passive = scan.scan_mode == "passive"
            container_id = bbot_runner.launch_bbot_scan(
                scan.id, scan.project_id, targets, blacklist, list(scan.modules), passive,
            )
            await db.execute(
                update(EASMScan)
                .where(EASMScan.id == scan_id)
                .values(status="running", container_id=container_id)
            )
            await db.commit()

        # Stream outside the session context — each event opens a short session
        byte_count = 0
        for event in bbot_runner.stream_bbot_logs(container_id):
            byte_count += len(str(event))
            async with async_session_factory() as db:
                scan = (
                    await db.execute(select(EASMScan).where(EASMScan.id == scan_id))
                ).scalar_one()
                await bbot_runner.persist_finding(db, scan.id, scan.project_id, event)

                # Promotion path
                bbot_type = event.get("type", "")
                data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
                severity = (data.get("severity") or "").upper() or None
                if easm_promoter.should_promote(bbot_type, severity):
                    # Load the finding to build promotion kwargs with server-side fields
                    chash = bbot_runner.content_hash_for(
                        scan.project_id, bbot_type, _canonical_target(event)
                    )
                    finding = await _load_finding_for(db, scan.project_id, bbot_type, chash)
                    if finding:
                        kwargs = easm_promoter.promote_finding_to_event(finding, scan)
                        # source_type is metadata only — not an ORM column on events
                        kwargs.pop("source_type", None)
                        # summary -> description column mapping
                        summary = kwargs.pop("summary", None)
                        kwargs["description"] = summary
                        db.add(Event(**kwargs))
                await db.commit()

        async with async_session_factory() as db:
            await db.execute(
                update(EASMScan)
                .where(EASMScan.id == scan_id)
                .values(status="finished", finished_at=_now(), stdout_bytes=byte_count)
            )
            await db.commit()

    except TimeLimitExceeded:
        if container_id:
            bbot_runner.cancel_bbot_container(container_id)
        async with async_session_factory() as db:
            await db.execute(
                update(EASMScan)
                .where(EASMScan.id == scan_id)
                .values(status="cancelled", finished_at=_now(), error="time_limit_exceeded")
            )
            await db.commit()
        raise
    except Exception as exc:
        log.exception("bbot_scan_failed scan_id=%s", scan_id)
        if container_id:
            bbot_runner.cancel_bbot_container(container_id)
        async with async_session_factory() as db:
            await _mark_scan_failed(db, scan_id, f"unhandled: {exc!r}"[:1024])
    finally:
        bbot_runner.release_semaphore(r)
        await local_engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _canonical_target(event: dict) -> str:
    """Extract canonical target string from a BBOT event dict.

    PITFALLS §Pitfall 6: data field is polymorphic — dict or plain string.
    """
    data = event.get("data", {})
    if isinstance(data, dict):
        return data.get("host") or data.get("url") or data.get("technology") or str(data)[:256]
    return str(data)[:256]


async def _mark_scan_failed(db, scan_id: uuid.UUID, reason: str) -> None:
    await db.execute(
        update(EASMScan)
        .where(EASMScan.id == scan_id)
        .values(status="failed", finished_at=_now(), error=reason)
    )
    await db.commit()


async def _load_finding_for(
    db, project_id: uuid.UUID, bbot_event_type: str, content_hash: str
) -> EASMFinding | None:
    stmt = select(EASMFinding).where(
        EASMFinding.project_id == project_id,
        EASMFinding.bbot_event_type == bbot_event_type,
        EASMFinding.content_hash == content_hash,
    )
    return (await db.execute(stmt)).scalar_one_or_none()
