"""WHOIS enrichment service — Phase 28 / ENRICH-07.

Fetches WHOIS registration data for a domain and caches it in whois_cache
with a 7-day refetch suppression gate. Uses asyncwhois for native async
WHOIS/RDAP lookup without a thread executor.

Rate-limit protection:
  - SQL TTL gate (7-day suppression) is the primary protection.
  - Per-domain Redis lock (SETNX, 5-min TTL) prevents concurrent workers
    querying the same domain simultaneously.
  - asyncwhois is NOT passed through quota.py (it's a protocol call, not an
    API-key-gated endpoint).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, date as date_type
from typing import Optional

import asyncwhois
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.passive_dns import WhoisCache

logger = logging.getLogger(__name__)

_WHOIS_LOCK_TTL = 300  # 5 minutes — prevents concurrent fetch of same domain
_WHOIS_TIMEOUT = 30.0  # seconds before asyncwhois gives up


def _coerce_date(val) -> Optional[date_type]:
    """Convert asyncwhois date values (datetime, list, or None) to date."""
    if val is None:
        return None
    if isinstance(val, list):
        val = val[0] if val else None
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date_type):
        return val
    return None


async def _do_fetch_whois(domain: str) -> dict | None:
    """Call asyncwhois.aio_whois() with timeout. Returns parsed dict or None."""
    try:
        _, parsed = await asyncio.wait_for(
            asyncwhois.aio_whois(domain, ignore_returned_errors=True),
            timeout=_WHOIS_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("whois_timeout domain=%s", domain)
        return None
    except Exception as exc:
        logger.warning("whois_error domain=%s error=%r", domain, exc)
        return None

    emails = parsed.get("emails") or []
    registrant_email = parsed.get("registrant_email") or (emails[0] if emails else None)
    # Normalise registrant_email: asyncwhois may return a list
    if isinstance(registrant_email, list):
        registrant_email = registrant_email[0] if registrant_email else None

    return {
        "registrar": parsed.get("registrar"),
        "registrant_email": registrant_email,
        "registration_date": _coerce_date(parsed.get("created")),
        "expiry_date": _coerce_date(parsed.get("expires")),
        "nameservers": parsed.get("name_servers") or [],
        "raw_json": {k: str(v) for k, v in parsed.items() if v is not None},
    }


async def fetch_and_cache_whois(
    session: AsyncSession,
    redis,
    domain: str,
) -> WhoisCache | None:
    """Fetch WHOIS for domain and upsert into whois_cache.

    Returns the WhoisCache row (existing or newly fetched), or None if the
    fetch failed and no cached row exists.

    7-day TTL gate: if a whois_cache row exists with fetched_at within the
    last 7 days, it is returned immediately without a network call.
    Per-domain Redis lock: prevents concurrent workers from double-fetching.
    """
    # 1. Check DB TTL gate — most common path, no Redis needed
    existing = (await session.execute(
        text(
            "SELECT id, domain, registrar, registrant_email, registration_date, "
            "expiry_date, nameservers, fetched_at, raw_json "
            "FROM whois_cache "
            "WHERE domain = :domain AND fetched_at + INTERVAL '7 days' > now()"
        ),
        {"domain": domain},
    )).mappings().first()

    if existing:
        logger.debug("whois_cache_hit domain=%s", domain)
        # Re-hydrate as a mapping row (matches WhoisCache column layout)
        return (await session.execute(
            text("SELECT * FROM whois_cache WHERE domain = :domain"),
            {"domain": domain},
        )).mappings().first()  # type: ignore[return-value]

    # 2. Acquire per-domain Redis lock (SETNX pattern)
    lock_key = f"whois:lock:{domain}"
    acquired = await redis.set(lock_key, "1", nx=True, ex=_WHOIS_LOCK_TTL)
    if not acquired:
        # Another worker is fetching — return existing stale row if any (or None)
        logger.debug("whois_lock_not_acquired domain=%s", domain)
        stale = (await session.execute(
            text("SELECT * FROM whois_cache WHERE domain = :domain"),
            {"domain": domain},
        )).mappings().first()
        return stale  # type: ignore[return-value]

    try:
        # 3. Fetch WHOIS data
        data = await _do_fetch_whois(domain)
        if data is None:
            return None

        # 4. Upsert into whois_cache (INSERT ON CONFLICT DO UPDATE)
        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(WhoisCache)
            .values(
                domain=domain,
                registrar=data["registrar"],
                registrant_email=data["registrant_email"],
                registration_date=data["registration_date"],
                expiry_date=data["expiry_date"],
                nameservers=data["nameservers"],
                raw_json=data["raw_json"],
                fetched_at=now,
            )
            .on_conflict_do_update(
                index_elements=["domain"],
                set_={
                    "registrar": data["registrar"],
                    "registrant_email": data["registrant_email"],
                    "registration_date": data["registration_date"],
                    "expiry_date": data["expiry_date"],
                    "nameservers": data["nameservers"],
                    "raw_json": data["raw_json"],
                    "fetched_at": now,
                },
            )
        )
        await session.execute(stmt)
        await session.commit()

        logger.info("whois_fetched domain=%s registrar=%s", domain, data.get("registrar"))

        return (await session.execute(
            text("SELECT * FROM whois_cache WHERE domain = :domain"),
            {"domain": domain},
        )).mappings().first()  # type: ignore[return-value]

    finally:
        await redis.delete(lock_key)


__all__ = ["fetch_and_cache_whois"]
