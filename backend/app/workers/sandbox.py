"""
— Sandbox submission and poll actors.
submit_sandbox_report: fetch sample, YARA scan, submit to provider, create pending report row.
poll_sandbox_report:   self-rescheduling poll with exponential backoff; writes result on completion.

CRITICAL: Never block with sleep() in these actors. Use send_with_options(delay=ms) for all waits.
CRITICAL: Create a fresh engine per actor invocation (_make_engine_and_session pattern from workers/ai.py).

Requirements: SANDBOX-02, SANDBOX-03, SANDBOX-05, YARA-02
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import uuid

import dramatiq
import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.models.iocs import IOC, IOCEventLink
from app.models.sandbox import SandboxConfig, SandboxReport as SandboxReportModel
from app.models.tags import AttackTechniqueTag
from app.services.sandbox import SandboxReport, get_provider_module
from app.services.sample_fetch import fetch_sample
from app.services.yara_engine import scan_sample, write_yara_matches

log = logging.getLogger(__name__)

BACKOFF_DELAYS_MS = [30_000, 60_000, 120_000, 300_000, 600_000]
MAX_POLL_ATTEMPTS = 30


# ---------------------------------------------------------------------------
# Per-loop engine helper — MANDATORY (see ai.py for canonical rationale)
# Each Dramatiq worker thread has its own asyncio event loop.
# A module-level engine would bind to the first loop and crash on subsequent calls.
# ---------------------------------------------------------------------------


def _make_engine_and_session():
    """Build a fresh async engine + session factory inside the running loop."""
    from app.config import settings  # noqa: PLC0415 — lazy import
    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        future=True,
        pool_size=2,
        max_overflow=2,
    )
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession,
    )
    return engine, session_factory


# ---------------------------------------------------------------------------
# Dramatiq actors
# ---------------------------------------------------------------------------


@dramatiq.actor(queue_name="sandbox", max_retries=0)
def submit_sandbox_report(ioc_id: str, project_id: str) -> None:
    """Submit a SHA256 IOC for sandbox detonation (SANDBOX-02).

    Flow:
      1. Load IOC row — bail if not sha256 type
      2. Check project sandbox config (enabled=True) — bail if not enabled
      3. fetch_sample() from MalwareBazaar (free) / VirusTotal Premium (fallback)
      4. If no sample → create sandbox_reports row with status='sample_unavailable'
      5. scan_sample() for YARA matches → write_yara_matches() if hits
      6. Submit to provider → create pending sandbox_reports row
      7. Queue poll_sandbox_report with 30s initial delay
    """
    try:
        asyncio.run(_async_submit(ioc_id, project_id))
    except Exception as exc:
        log.exception("submit_sandbox_report_failed ioc_id=%s error=%r", ioc_id, exc)
        raise


@dramatiq.actor(queue_name="sandbox", max_retries=0)
def poll_sandbox_report(report_id: str, submitted_at_iso: str, attempt: int) -> None:
    """Poll sandbox for detonation result; self-reschedules with exponential backoff (SANDBOX-03).

    Flow:
      1. Load SandboxReport by (id, submitted_at) composite PK
      2. Call provider.poll() — if None (still running):
         a. attempt < MAX_POLL_ATTEMPTS → re-queue with backoff delay
         b. attempt >= MAX_POLL_ATTEMPTS → set status='timeout'
      3. On result → _write_sandbox_result() then commit
    """
    try:
        asyncio.run(_async_poll(report_id, submitted_at_iso, attempt))
    except Exception as exc:
        log.exception(
            "poll_sandbox_report_failed report_id=%s attempt=%s error=%r",
            report_id, attempt, exc,
        )
        raise


# ---------------------------------------------------------------------------
# Async implementations
# ---------------------------------------------------------------------------


async def _async_submit(ioc_id: str, project_id: str) -> None:
    engine, session_factory = _make_engine_and_session()
    try:
        async with session_factory() as db:
            # Load IOC with event_links (IOC has no event_id column; get via relationship)
            result = await db.execute(
                select(IOC)
                .where(IOC.id == uuid.UUID(ioc_id))
                .options(selectinload(IOC.event_links))
            )
            ioc = result.scalar_one_or_none()
            if ioc is None or ioc.type != "sha256":
                return

            # event_id is on IOCEventLink, not on IOC directly
            _event_id = ioc.event_links[0].event_id if ioc.event_links else None

            # Check sandbox config
            result = await db.execute(
                select(SandboxConfig).where(
                    SandboxConfig.project_id == uuid.UUID(project_id),
                    SandboxConfig.enabled.is_(True),
                )
            )
            config = result.scalar_one_or_none()
            if config is None:
                log.debug("sandbox_disabled project_id=%s ioc_id=%s", project_id, ioc_id)
                return

            # Decrypt API key
            api_key = _decrypt_api_key(config.api_key_enc)

            # Fetch VT key if available (Premium fallback for sample download)
            vt_key = await _get_vt_key(db, uuid.UUID(project_id))

            # Fetch sample bytes — MalwareBazaar first, VT Premium fallback
            async with httpx.AsyncClient() as client:
                sample_data = await fetch_sample(client, ioc.normalized_value, vt_key)

            if sample_data is None:
                report_row = SandboxReportModel(
                    event_id=_event_id,
                    project_id=uuid.UUID(project_id),
                    provider=config.provider,
                    status="sample_unavailable",
                    sha256=ioc.normalized_value,
                    error_detail="sample_unavailable: not found in MalwareBazaar or VirusTotal Premium",
                )
                db.add(report_row)
                await db.commit()
                log.info("sandbox_sample_unavailable sha256=%.16s", ioc.normalized_value)
                return

            # YARA scan in memory before sandbox submission — no disk writes
            yara_matches = await scan_sample(db, uuid.UUID(project_id), sample_data)
            if _event_id and yara_matches:
                await write_yara_matches(db, yara_matches, _event_id, scan_context="sample")

            # Submit to sandbox provider
            try:
                provider_mod = get_provider_module(config.provider)
                async with httpx.AsyncClient() as client:
                    job_id = await provider_mod.submit(
                        client, ioc.normalized_value, api_key, config.options
                    )
            except Exception as exc:
                log.error(
                    "sandbox_submit_error provider=%s sha256=%.16s error=%r",
                    config.provider, ioc.normalized_value, exc,
                )
                report_row = SandboxReportModel(
                    event_id=_event_id,
                    project_id=uuid.UUID(project_id),
                    provider=config.provider,
                    status="error",
                    sha256=ioc.normalized_value,
                    error_detail=str(exc),
                )
                db.add(report_row)
                await db.commit()
                return

            # Create pending report row
            now = datetime.datetime.now(tz=datetime.timezone.utc)
            report_row = SandboxReportModel(
                event_id=_event_id,
                project_id=uuid.UUID(project_id),
                provider=config.provider,
                job_id=job_id,
                status="pending",
                sha256=ioc.normalized_value,
                submitted_at=now,
            )
            db.add(report_row)
            await db.commit()
            await db.refresh(report_row)

            # Queue initial poll with 30s delay (BACKOFF_DELAYS_MS[0])
            poll_sandbox_report.send_with_options(
                args=(str(report_row.id), report_row.submitted_at.isoformat(), 0),
                delay=BACKOFF_DELAYS_MS[0],
            )
            log.info(
                "sandbox_submitted provider=%s job_id=%s sha256=%.16s",
                config.provider, job_id, ioc.normalized_value,
            )
    finally:
        await engine.dispose()


async def _async_poll(report_id: str, submitted_at_iso: str, attempt: int) -> None:
    engine, session_factory = _make_engine_and_session()
    try:
        async with session_factory() as db:
            submitted_at = datetime.datetime.fromisoformat(submitted_at_iso)
            result = await db.execute(
                select(SandboxReportModel).where(
                    SandboxReportModel.id == uuid.UUID(report_id),
                    SandboxReportModel.submitted_at == submitted_at,
                )
            )
            report = result.scalar_one_or_none()
            if report is None or report.status in (
                "complete", "timeout", "error", "sample_unavailable"
            ):
                return

            result2 = await db.execute(
                select(SandboxConfig).where(SandboxConfig.project_id == report.project_id)
            )
            config = result2.scalar_one_or_none()
            if config is None:
                return

            api_key = _decrypt_api_key(config.api_key_enc)
            provider_mod = get_provider_module(report.provider)

            sandbox_result = None
            async with httpx.AsyncClient() as client:
                try:
                    sandbox_result = await provider_mod.poll(
                        client, report.job_id, api_key, config.options
                    )
                except Exception as exc:
                    log.error(
                        "sandbox_poll_error report_id=%s attempt=%s error=%r",
                        report_id, attempt, exc,
                    )

            if sandbox_result is None:
                # Still running — increment attempt counter
                report.poll_attempts = attempt + 1
                if attempt + 1 >= MAX_POLL_ATTEMPTS:
                    report.status = "timeout"
                    await db.commit()
                    log.warning(
                        "sandbox_timeout report_id=%s attempts=%d",
                        report_id, attempt + 1,
                    )
                    return
                delay_idx = min(attempt, len(BACKOFF_DELAYS_MS) - 1)
                await db.commit()
                poll_sandbox_report.send_with_options(
                    args=(report_id, submitted_at_iso, attempt + 1),
                    delay=BACKOFF_DELAYS_MS[delay_idx],
                )
                return

            # Complete — write result and commit
            await _write_sandbox_result(db, report, sandbox_result)
            await db.commit()
            log.info(
                "sandbox_complete report_id=%s verdict=%s score=%s",
                report_id, sandbox_result.verdict, sandbox_result.score,
            )
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# _write_sandbox_result — writes report row, auto-tags techniques, upserts IOCs
# ---------------------------------------------------------------------------


async def _write_sandbox_result(
    db: AsyncSession,
    report: SandboxReportModel,
    result: SandboxReport,
) -> None:
    """Write completed sandbox result: update report row, auto-tag techniques, upsert network IOCs.

    NOTE: Uses direct pg_insert for both AttackTechniqueTag and IOC rows.
    upsert_ioc_for_event_sync/upsert_ioc_for_event take an event_row+enrichment bundle —
    their signatures are incompatible with per-IOC value insertion from a sandbox report.
    Direct pg_insert(IOC.__table__).on_conflict_do_nothing() is the correct pattern here.
    """
    report.status = "complete"
    report.report_json = result.raw_json
    report.techniques = result.techniques
    report.network_iocs = result.network_iocs
    report.process_tree = result.process_tree
    report.score = result.score
    report.verdict = result.verdict
    report.completed_at = datetime.datetime.now(tz=datetime.timezone.utc)

    # Auto-tag MITRE ATT&CK techniques from sandbox report (SANDBOX-05)
    if report.event_id and result.techniques:
        for technique_id in result.techniques:
            await db.execute(
                pg_insert(AttackTechniqueTag.__table__).values(
                    event_id=report.event_id,
                    technique_id=technique_id,
                    tag_source="auto",
                    evidence_text=f"Sandbox: {report.provider} job {report.job_id}",
                ).on_conflict_do_nothing()
            )

    # Upsert network IOCs extracted from sandbox report
    # IOC table has no event_id column — link is via IOCEventLink junction table
    if result.network_iocs:
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        for raw_ioc in result.network_iocs:
            try:
                ioc_type = _classify_ioc(raw_ioc)
                if ioc_type:
                    ioc_id = uuid.uuid4()
                    await db.execute(
                        pg_insert(IOC.__table__).values(
                            id=ioc_id,
                            project_id=report.project_id,
                            type=ioc_type,
                            value=raw_ioc,
                            normalized_value=raw_ioc,
                            confidence=0.8,
                            source="event",
                            ttl_days=30,
                            first_seen=now,
                            last_seen=now,
                        ).on_conflict_do_nothing()
                    )
                    if report.event_id:
                        await db.execute(
                            pg_insert(IOCEventLink.__table__).values(
                                id=uuid.uuid4(),
                                ioc_id=ioc_id,
                                event_id=report.event_id,
                            ).on_conflict_do_nothing()
                        )
            except Exception as exc:
                log.warning("sandbox_ioc_upsert_error value=%s error=%r", raw_ioc, exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify_ioc(value: str) -> str | None:
    """Classify a raw network IOC string into ip/domain/url type."""
    import re
    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", value):
        return "ip"
    if value.startswith("http://") or value.startswith("https://"):
        return "url"
    if re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$", value):
        return "domain"
    return None


def _decrypt_api_key(credentials_enc: str | None) -> str | None:
    """Decrypt stored API key — same pattern as enrichment workers."""
    if not credentials_enc:
        return None
    try:
        from app.config import settings  # noqa: PLC0415
        from app.crypto import decrypt_credentials  # noqa: PLC0415
        creds = decrypt_credentials(settings.SECRET_KEY, credentials_enc)
        if creds.get("type") == "apiKey":
            return creds.get("key")
    except Exception as exc:
        log.warning("decrypt_api_key_error error=%r", exc)
    return None


async def _get_vt_key(db: AsyncSession, project_id: uuid.UUID) -> str | None:
    """Fetch VirusTotal API key from project enrichment providers if configured."""
    try:
        from app.models.enrichment import EnrichmentProvider  # noqa: PLC0415
        result = await db.execute(
            select(EnrichmentProvider).where(
                EnrichmentProvider.project_id == project_id,
                EnrichmentProvider.provider == "virustotal",
                EnrichmentProvider.enabled.is_(True),
            )
        )
        row = result.scalar_one_or_none()
        if row:
            return _decrypt_api_key(row.credentials_enc)
    except Exception:  # noqa: BLE001
        pass
    return None
