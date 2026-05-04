"""Mnemonic PassiveDNS provider — Phase 28 / ENRICH-06.

Supports: domain

Returns list[dict] | None where each dict:
  {"ip": str, "first_seen": datetime|None, "last_seen": datetime|None, "source": str}

API docs: https://api.mnemonic.no/pdns/v3/
  GET /pdns/v3/{domain}
  Optional header: Argus-API-Key: <api_key>

CRITICAL: Mnemonic timestamps are epoch MILLISECONDS — divide by 1000 before fromtimestamp().
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx

from app.services.enrichment.circuit_breaker import (
    is_breaker_open,
    record_quota_failure,
    record_success,
)
from app.services.enrichment.quota import (
    check_and_consume_quota,
    PROVIDER_MINUTE_CAPS,
    PROVIDER_DEFAULT_DAILY_CAPS,
)

logger = logging.getLogger(__name__)
PROVIDER = "mnemonic"
_BASE = "https://api.mnemonic.no"
_SUPPORTED_TYPES = {"domain"}
_CACHE_TTL = 86_400  # 24 hours in seconds


async def _get_cached_pdns(redis, domain: str) -> list[dict] | None:
    key = f"enrich:pdns:mnemonic:{domain}"
    raw = await redis.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def _cache_pdns(redis, domain: str, rows: list[dict]) -> None:
    key = f"enrich:pdns:mnemonic:{domain}"
    serialisable = [
        {
            "ip": r["ip"],
            "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
            "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
            "source": r["source"],
        }
        for r in rows
    ]
    await redis.set(key, json.dumps(serialisable), ex=_CACHE_TTL, nx=True)


def _deserialise_rows(raw_rows: list[dict]) -> list[dict]:
    """Convert cached ISO strings back to datetime objects."""
    return [
        {
            "ip": r["ip"],
            "first_seen": datetime.fromisoformat(r["first_seen"]) if r["first_seen"] else None,
            "last_seen": datetime.fromisoformat(r["last_seen"]) if r["last_seen"] else None,
            "source": r["source"],
        }
        for r in raw_rows
    ]


async def enrich_pdns(
    client: httpx.AsyncClient,
    redis,
    api_key: str | None,
    domain: str,
    project_scope: str,
    daily_cap: int | None = None,
) -> list[dict] | None:
    """Fetch passive DNS records from Mnemonic PassiveDNS.

    Returns list[dict] (may be empty) or None on error/gate.
    Each dict: {"ip": str, "first_seen": datetime|None, "last_seen": datetime|None, "source": str}
    """
    # 1. Circuit breaker
    if await is_breaker_open(redis, PROVIDER, project_scope):
        return None

    # 2. Redis cache (24h)
    cached = await _get_cached_pdns(redis, domain)
    if cached is not None:
        logger.debug("mnemonic_pdns_cache_hit domain=%s", domain)
        return _deserialise_rows(cached)

    # 3. Quota check
    cap = daily_cap if daily_cap is not None else PROVIDER_DEFAULT_DAILY_CAPS[PROVIDER]
    allowed = await check_and_consume_quota(
        redis, PROVIDER, project_scope,
        minute_cap=PROVIDER_MINUTE_CAPS[PROVIDER],
        daily_cap=cap,
    )
    if not allowed:
        return None

    # 4. API call
    url = f"{_BASE}/pdns/v3/{domain}"
    headers: dict[str, str] = {}
    if api_key:
        headers["Argus-API-Key"] = api_key

    try:
        response = await client.get(url, headers=headers, timeout=10.0)
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.warning("mnemonic_request_error domain=%s error=%r", domain, exc)
        return None

    if response.status_code == 429:
        await record_quota_failure(redis, PROVIDER, project_scope)
        return None
    if response.status_code != 200:
        logger.debug("mnemonic_non200 status=%d domain=%s", response.status_code, domain)
        return None

    rows: list[dict] = []
    for rec in response.json().get("data", []):
        if rec.get("rrtype") not in ("A", "AAAA"):
            continue
        # CRITICAL: timestamps are epoch milliseconds — divide by 1000
        first_seen_ms = rec.get("firstSeenTimestamp")
        last_seen_ms = rec.get("lastSeenTimestamp")
        rows.append(
            {
                "ip": rec["answer"],
                "first_seen": (
                    datetime.fromtimestamp(first_seen_ms / 1000, tz=timezone.utc)
                    if first_seen_ms is not None
                    else None
                ),
                "last_seen": (
                    datetime.fromtimestamp(last_seen_ms / 1000, tz=timezone.utc)
                    if last_seen_ms is not None
                    else None
                ),
                "source": PROVIDER,
            }
        )

    await _cache_pdns(redis, domain, rows)
    await record_success(redis, PROVIDER, project_scope)
    return rows
