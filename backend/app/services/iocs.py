"""IOC services: per-type normalisation + TTL defaults — IOC-01.

Single source of truth for canonical-value transforms. Reused by:
  * ingest hook (Plan 22-04) — auto-IOC writes from event extraction
  * bulk import parsers (Plan 22-05) — CSV / JSON / STIX
  * backfill (Plan 22-04) — admin endpoint over historical events

Normalisation contract (per 22-CONTEXT.md "Claude's Discretion"):
  * IPs → ipaddress canonical compressed form (IPv6 collapses)
  * Domains → idna.encode(uts46=True, transitional=False).decode().lower()
  * URLs → lowercase scheme + host; path/query/fragment case preserved
  * Hashes (sha256/sha1/md5) → lowercase hex
  * Emails → lowercase entire address
  * btc / eth / mutex / filename / registry_key → trimmed; case preserved
    (registry keys are case-sensitive on Windows; preserve)

The function NEVER raises — malformed input falls back to `value.strip().lower()`
or `value.strip()` (for case-preserving types). This keeps backfill / bulk-import
robust on imperfect partner-shared data; analyst can fix or whitelist later.
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

import idna

# Locked at migration 023 — the ENUM and this tuple must stay in sync.
IOC_TYPE_ENUM_VALUES: tuple[str, ...] = (
    "ip", "ipv6", "domain", "url",
    "sha256", "sha1", "md5",
    "email", "btc", "eth", "mutex", "registry_key", "filename",
)

# Type-aware default ttl_days (per 22-CONTEXT.md §"TTL decay defaults").
# Analyst override per row via IOCCreate.ttl_days / IOCPatch.ttl_days.
IOC_TTL_DEFAULTS: dict[str, int] = {
    "ip": 30, "ipv6": 30, "url": 30,
    "domain": 180, "email": 180, "filename": 180,
    "sha256": 365, "sha1": 365, "md5": 365,
    "mutex": 365, "registry_key": 365,
    "btc": 730, "eth": 730,
}


def normalise(ioc_type: str, value: str) -> str:
    """Return the canonical-form normalized_value for storage and dedup.

    Never raises — malformed input falls back to a lowercased trim
    (case-preserved for btc / eth / mutex / filename / registry_key).
    """
    v = (value or "").strip()
    if not v:
        return v

    if ioc_type == "ip":
        # Python 3.10+ rejects octets with leading zeros (per RFC 5321 ambiguity).
        # Partner-shared CSVs often emit padded octets (`01.02.03.04`); strip
        # leading zeros per-octet before delegating to ipaddress for canonicalisation.
        try:
            parts = v.split(".")
            if len(parts) == 4 and all(p.isdigit() for p in parts):
                v_stripped = ".".join(str(int(p)) for p in parts)
            else:
                v_stripped = v
            return str(ipaddress.IPv4Address(v_stripped).compressed)
        except (ipaddress.AddressValueError, ValueError):
            return v.lower()

    if ioc_type == "ipv6":
        try:
            return str(ipaddress.IPv6Address(v).compressed)
        except (ipaddress.AddressValueError, ValueError):
            return v.lower()

    if ioc_type == "domain":
        try:
            return idna.encode(v, uts46=True, transitional=False).decode("ascii").lower()
        except idna.IDNAError:
            return v.lower()

    if ioc_type == "url":
        try:
            p = urlparse(v)
            tail = p.path or ""
            if p.query:
                tail = f"{tail}?{p.query}"
            if p.fragment:
                tail = f"{tail}#{p.fragment}"
            return f"{p.scheme.lower()}://{p.netloc.lower()}{tail}"
        except Exception:
            return v

    if ioc_type in ("sha256", "sha1", "md5"):
        return v.lower()

    if ioc_type == "email":
        return v.lower()

    # btc / eth / mutex / filename / registry_key — case preserved
    return v


# ---------------------------------------------------------------------------
# Plan 22-04 additions: upsert + expire + backfill + clone-on-whitelist
#
# `upsert_ioc_for_event_sync` services the ingest hook (`_persist_event` is a
# SYNC function — the existing helpers in `app/ingest/normalise.py` use a sync
# Session, so the IOC writer must too). The async variant is used by the
# Dramatiq backfill actor and the seed_iocs CLI.
#
# Re-sighting contract (CONTEXT.md §"Re-sighting upsert" + RESEARCH Pitfall 5):
#   ON CONFLICT (project_id, type, normalized_value) DO UPDATE SET
#     last_seen = GREATEST(iocs.last_seen, EXCLUDED.last_seen),
#     status = CASE WHEN iocs.status='expired' THEN 'active' ELSE iocs.status END,
#     updated_at = NOW()
#   confidence + ttl_days are NEVER in the SET clause. Whitelist state stays.
# ---------------------------------------------------------------------------

import uuid as _uuid
from datetime import datetime as _dt, timezone as _tz
from decimal import Decimal as _Decimal
from typing import Any as _Any

from sqlalchemy import select as _select, text as _text
from sqlalchemy.dialects.postgresql import insert as _pg_insert
from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
from sqlalchemy.orm import Session as _SyncSession

from app.models.iocs import IOC as _IOC, IOCEventLink as _IOCLink

# Map enrichment.py 'hash' bucket → sha256/sha1/md5 by char length.
_HASH_LEN_MAP: dict[int, str] = {64: "sha256", 40: "sha1", 32: "md5"}

# Map enrichment.py keys → ioc_type_enum slot.
_ENRICHMENT_KEY_MAP: dict[str, str] = {
    "ip": "ip", "ipv6": "ipv6", "domain": "domain",
    "url": "url", "email": "email", "btc": "btc", "eth": "eth",
}


def _classify_enrichment_iocs(enrichment: _Any) -> list[tuple[str, str]]:
    """Return a list of (ioc_type, raw_value) pairs from an `Enrichment` object.

    Hash bucket is split by length (64=sha256, 40=sha1, 32=md5; other lengths
    skipped). Unknown keys are ignored.
    """
    out: list[tuple[str, str]] = []
    e_iocs = getattr(enrichment, "iocs", {}) or {}
    for key, values in e_iocs.items():
        mapped = _ENRICHMENT_KEY_MAP.get(key)
        if mapped is not None:
            for v in values:
                if v:
                    out.append((mapped, v))
        elif key == "hash":
            for v in values:
                t = _HASH_LEN_MAP.get(len(v or ""))
                if t:
                    out.append((t, v))
    return out


def _build_ioc_insert_stmt(
    *, project_id: _uuid.UUID | None, ioc_type: str, raw_value: str,
    normalized: str, confidence: _Decimal, ttl: int, source: str,
    observed_at: _dt, now: _dt, created_by: str | None = None,
):
    """Compose the per-IOC INSERT…ON CONFLICT statement (shared sync/async)."""
    return _pg_insert(_IOC).values(
        project_id=project_id,
        type=ioc_type,
        value=raw_value,
        normalized_value=normalized,
        status="active",
        confidence=confidence,
        ttl_days=ttl,
        source=source,
        first_seen=observed_at,
        last_seen=observed_at,
        created_at=now,
        updated_at=now,
        created_by=created_by,
    ).on_conflict_do_update(
        index_elements=[_IOC.project_id, _IOC.type, _IOC.normalized_value],
        set_={
            "last_seen": _text("GREATEST(iocs.last_seen, EXCLUDED.last_seen)"),
            "status": _text(
                "CASE WHEN iocs.status='expired' THEN 'active' "
                "ELSE iocs.status END"
            ),
            "updated_at": _text("NOW()"),
        },
    ).returning(_IOC.id)


def upsert_ioc_for_event_sync(
    session: _SyncSession,
    event_row: _Any,
    enrichment: _Any,
    *,
    source: str = "event",
    confidence_override: _Decimal | None = None,
) -> tuple[int, int]:
    """Sync ingest-time IOC writer used by `_persist_event`.

    Mirrors `upsert_ioc_for_event` (async) but uses the existing sync session.
    Returns ``(iocs_upserted, links_inserted)``.

    `event_row` may be either an ORM Event or a row dict with keys ``id``,
    ``project_id``, ``observed_at``, ``title``, ``description``. The `_persist_event`
    helper hands us the result of `RETURNING (id, observed_at)` plus the original
    row dict, so we accept both shapes.
    """
    pairs = _classify_enrichment_iocs(enrichment)
    if not pairs:
        return 0, 0

    # Tolerate either ORM-style or dict-style event reps.
    if isinstance(event_row, dict):
        event_id = event_row.get("id")
        project_id = event_row.get("project_id")
        observed_at = event_row.get("observed_at")
    else:
        event_id = getattr(event_row, "id", None)
        project_id = getattr(event_row, "project_id", None)
        observed_at = getattr(event_row, "observed_at", None)

    if event_id is None:
        return 0, 0
    now = _dt.now(_tz.utc)
    if observed_at is None:
        observed_at = now

    iocs_upserted = 0
    links_inserted = 0
    for ioc_type, raw_value in pairs:
        try:
            normalized = normalise(ioc_type, raw_value)
        except Exception:  # noqa: BLE001
            continue
        if not normalized:
            continue
        ttl = IOC_TTL_DEFAULTS.get(ioc_type, 90)
        confidence = (
            confidence_override
            if confidence_override is not None
            else _Decimal("0.7")
        )
        stmt = _build_ioc_insert_stmt(
            project_id=project_id,
            ioc_type=ioc_type,
            raw_value=raw_value,
            normalized=normalized,
            confidence=confidence,
            ttl=ttl,
            source=source,
            observed_at=observed_at,
            now=now,
        )
        try:
            res = session.execute(stmt)
            ioc_id = res.scalar_one()
        except Exception:  # noqa: BLE001
            # Best-effort — never break ingest on a single bad IOC row.
            continue
        iocs_upserted += 1

        # Enqueue enrichment immediately after successful IOC upsert.
        # The whitelisted/type check happens inside _async_enrich — always enqueue.
        # Cache absorbs re-sights at worker level (no quota burn per RESEARCH.md §Pitfall 3).
        try:
            from app.workers.iocs import enrich_ioc as _enrich_ioc  # noqa: PLC0415 — lazy, avoids circular
            _enrich_ioc.send(str(ioc_id))
        except Exception as _enq_exc:  # noqa: BLE001
            import logging as _logging  # noqa: PLC0415
            _logging.getLogger(__name__).warning(
                "enrich_ioc_enqueue_failed ioc_id=%s error=%r", ioc_id, _enq_exc
            )

        # Trigger sandbox analysis for SHA256 IOCs (SANDBOX-02).
        # trigger_sandbox_if_sha256 checks ioc_type internally; safe to call on all types.
        try:
            from app.workers.iocs import trigger_sandbox_if_sha256 as _trigger_sandbox  # noqa: PLC0415
            _trigger_sandbox(str(ioc_id), ioc_type, str(project_id))
        except Exception as _sandbox_exc:  # noqa: BLE001
            import logging as _logging  # noqa: PLC0415
            _logging.getLogger(__name__).warning(
                "trigger_sandbox_enqueue_failed ioc_id=%s error=%r", ioc_id, _sandbox_exc
            )

        link_stmt = (
            _pg_insert(_IOCLink)
            .values(
                ioc_id=ioc_id,
                event_id=event_id,
                observed_at=observed_at,
                source_field="title+description",
            )
            .on_conflict_do_nothing(constraint="uq_ioc_event_links_ioc_event")
        )
        try:
            link_res = session.execute(link_stmt)
            links_inserted += link_res.rowcount or 0
        except Exception:  # noqa: BLE001
            continue

    return iocs_upserted, links_inserted


async def upsert_ioc_for_event(
    session: _AsyncSession,
    event_row: _Any,
    enrichment: _Any,
    *,
    source: str = "event",
    confidence_override: _Decimal | None = None,
) -> tuple[int, int]:
    """Async variant — used by the backfill path."""
    pairs = _classify_enrichment_iocs(enrichment)
    if not pairs:
        return 0, 0

    if isinstance(event_row, dict):
        event_id = event_row.get("id")
        project_id = event_row.get("project_id")
        observed_at = event_row.get("observed_at")
    else:
        event_id = getattr(event_row, "id", None)
        project_id = getattr(event_row, "project_id", None)
        observed_at = getattr(event_row, "observed_at", None)

    if event_id is None:
        return 0, 0
    now = _dt.now(_tz.utc)
    if observed_at is None:
        observed_at = now

    iocs_upserted = 0
    links_inserted = 0
    for ioc_type, raw_value in pairs:
        try:
            normalized = normalise(ioc_type, raw_value)
        except Exception:  # noqa: BLE001
            continue
        if not normalized:
            continue
        ttl = IOC_TTL_DEFAULTS.get(ioc_type, 90)
        confidence = (
            confidence_override
            if confidence_override is not None
            else _Decimal("0.7")
        )
        stmt = _build_ioc_insert_stmt(
            project_id=project_id,
            ioc_type=ioc_type,
            raw_value=raw_value,
            normalized=normalized,
            confidence=confidence,
            ttl=ttl,
            source=source,
            observed_at=observed_at,
            now=now,
        )
        try:
            res = await session.execute(stmt)
            ioc_id = res.scalar_one()
        except Exception:  # noqa: BLE001
            continue
        iocs_upserted += 1

        link_stmt = (
            _pg_insert(_IOCLink)
            .values(
                ioc_id=ioc_id,
                event_id=event_id,
                observed_at=observed_at,
                source_field="title+description",
            )
            .on_conflict_do_nothing(constraint="uq_ioc_event_links_ioc_event")
        )
        try:
            link_res = await session.execute(link_stmt)
            links_inserted += link_res.rowcount or 0
        except Exception:  # noqa: BLE001
            continue

    return iocs_upserted, links_inserted


async def expire_iocs(session: _AsyncSession) -> int:
    """Soft-expire active IOCs whose TTL has elapsed (IOC-05).

    Returns the number of rows flipped to status='expired'. The caller is
    responsible for owning the session; this helper commits its own UPDATE.
    """
    result = await session.execute(
        _text(
            "UPDATE iocs SET status='expired', updated_at=NOW() "
            "WHERE status='active' "
            "  AND last_seen + (ttl_days * INTERVAL '1 day') < NOW()"
        )
    )
    await session.commit()
    return result.rowcount or 0


async def backfill_iocs_for_project(
    session: _AsyncSession,
    project_id: _uuid.UUID | None = None,
    batch_size: int = 1000,
) -> dict[str, int]:
    """Re-runnable backfill over `events`. Idempotent — second run produces
    ~0 net new IOC rows because the upsert preserves confidence on conflict.

    Confidence inheritance (CONTEXT.md §Backfill strategy):
      * `events.source_id` -> `sources.confidence` (NVD=1.0, RSS=0.7…)
      * LEGACY events with `source_id IS NULL` → flat 0.5

    Returns ``{events_processed, iocs_inserted}``. Streamed in `batch_size`
    chunks; each batch commits independently so a long backfill makes
    incremental progress visible to monitoring queries.
    """
    from app.services.enrichment import enrich_event  # noqa: PLC0415
    from app.models.events import Event  # noqa: PLC0415
    from app.models.sources import Source  # noqa: PLC0415

    events_processed = 0
    iocs_inserted = 0
    offset = 0
    while True:
        stmt = (
            _select(Event, Source.confidence.label("source_confidence"))
            .outerjoin(Source, Source.id == Event.source_id)
            .order_by(Event.id)
            .offset(offset)
            .limit(batch_size)
        )
        if project_id is not None:
            stmt = stmt.where(Event.project_id == project_id)
        rows = (await session.execute(stmt)).all()
        if not rows:
            break
        for event_obj, source_conf in rows:
            try:
                enrichment = enrich_event(
                    getattr(event_obj, "title", None) or "",
                    getattr(event_obj, "description", None) or "",
                )
            except Exception:  # noqa: BLE001
                events_processed += 1
                continue
            inferred_conf = (
                _Decimal(str(source_conf))
                if source_conf is not None
                else _Decimal("0.5")
            )
            inserted, _links = await upsert_ioc_for_event(
                session,
                event_obj,
                enrichment,
                source="backfill",
                confidence_override=inferred_conf,
            )
            iocs_inserted += inserted
            events_processed += 1
        await session.commit()
        offset += batch_size

    return {"events_processed": events_processed, "iocs_inserted": iocs_inserted}


async def clone_global_to_project_whitelisted(
    session: _AsyncSession,
    global_ioc: _Any,
    project_id: _uuid.UUID,
    user_sub: str | None,
) -> _uuid.UUID:
    """Clone-on-whitelist (non-admin Lead suppressing a global row).

    Per CONTEXT.md §"Whitelist scope per-row": two rows with the same
    (type, normalized_value) keep independent whitelist state. A Lead who
    finds a global IOC noisy in their engagement clones it into their
    project_id with status='whitelisted'; the global row is unchanged.

    Returns the per-project IOC id (newly inserted, or the existing
    per-project shadow row's id if one already existed).
    """
    now = _dt.now(_tz.utc)
    stmt = _pg_insert(_IOC).values(
        project_id=project_id,
        type=global_ioc.type,
        value=global_ioc.value,
        normalized_value=global_ioc.normalized_value,
        status="whitelisted",
        confidence=global_ioc.confidence,
        ttl_days=global_ioc.ttl_days,
        source=global_ioc.source,
        first_seen=global_ioc.first_seen,
        last_seen=global_ioc.last_seen,
        created_at=now,
        updated_at=now,
        created_by=user_sub,
    ).on_conflict_do_update(
        index_elements=[_IOC.project_id, _IOC.type, _IOC.normalized_value],
        set_={"status": "whitelisted", "updated_at": now},
    ).returning(_IOC.id)
    res = await session.execute(stmt)
    new_id = res.scalar_one()
    await session.commit()
    return new_id


# ---------------------------------------------------------------------------
# Plan 22-05 addition: per-row bulk-import upsert with deterministic counter.
#
# The bulk-import Dramatiq actor needs to know whether each row was an INSERT
# or an UPDATE so it can populate `inserted/updated/skipped` in the Redis job
# status. The system-column-based introspection approach was rejected on
# revision (checker warning #7) — replaced here with a deterministic
# SELECT-then-upsert pattern: the existence check runs in the SAME transaction
# as the upsert, so it sees the actor's prior batch writes and never
# double-counts.
# ---------------------------------------------------------------------------


async def upsert_ioc_row(
    session: _AsyncSession,
    row: _Any,
    *,
    project_id: _uuid.UUID | None,
    source: str,
    user_sub: str | None,
) -> str:
    """Bulk-import per-row upsert. Returns 'inserted' | 'updated' | 'skipped'.

    Implementation: SELECT the existence of `(project_id, type, normalized_value)`
    against the same predicate as the UNIQUE NULLS NOT DISTINCT index, then
    perform the upsert. The pre-SELECT shares the actor's transaction so it
    sees prior batch writes — no system-column introspection needed (per
    IntelliBird revision; checker warning #7).

    Re-sighting semantics preserved: confidence + ttl_days are NEVER in the
    ON CONFLICT SET clause (CONTEXT.md §"Re-sighting upsert").
    """
    normalized = normalise(row.type, row.value)
    if not normalized:
        return "skipped"
    ttl = (
        row.ttl_days
        if getattr(row, "ttl_days", None) is not None
        else IOC_TTL_DEFAULTS.get(row.type, 90)
    )
    confidence = (
        row.confidence
        if getattr(row, "confidence", None) is not None
        else _Decimal("0.7")
    )
    now = _dt.now(_tz.utc)
    first_seen = getattr(row, "first_seen", None) or now
    last_seen = getattr(row, "last_seen", None) or now

    # Step 1: deterministic existence check (mirrors the UNIQUE index).
    existence_stmt = _select(_IOC.id).where(
        _IOC.project_id.is_(None) if project_id is None else _IOC.project_id == project_id,
        _IOC.type == row.type,
        _IOC.normalized_value == normalized,
    )
    existing = (await session.execute(existence_stmt)).scalars().first()
    outcome = "updated" if existing is not None else "inserted"

    # Step 2: upsert (re-sighting safe — confidence/ttl_days unchanged on conflict).
    stmt = (
        _pg_insert(_IOC)
        .values(
            project_id=project_id,
            type=row.type,
            value=row.value,
            normalized_value=normalized,
            status="active",
            confidence=confidence,
            ttl_days=ttl,
            source=source,
            first_seen=first_seen,
            last_seen=last_seen,
            created_at=now,
            updated_at=now,
            created_by=user_sub,
        )
        .on_conflict_do_update(
            index_elements=[_IOC.project_id, _IOC.type, _IOC.normalized_value],
            set_={
                "last_seen": _text("GREATEST(iocs.last_seen, EXCLUDED.last_seen)"),
                "status": _text(
                    "CASE WHEN iocs.status='expired' THEN 'active' ELSE iocs.status END"
                ),
                "updated_at": _text("NOW()"),
            },
        )
    )
    await session.execute(stmt)
    return outcome


__all__ = [
    "normalise",
    "IOC_TYPE_ENUM_VALUES",
    "IOC_TTL_DEFAULTS",
    "upsert_ioc_for_event",
    "upsert_ioc_for_event_sync",
    "upsert_ioc_row",
    "expire_iocs",
    "backfill_iocs_for_project",
    "clone_global_to_project_whitelisted",
]
