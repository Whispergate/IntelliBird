"""SecurityTrails passive DNS provider — Phase 28 / ENRICH-06.

Supports: domain

Returns list[dict] | None where each dict:
  {"ip": str, "first_seen": datetime|None, "last_seen": datetime|None, "source": str}

API docs: https://docs.securitytrails.com/reference/history-dns
  GET /v1/history/{hostname}/dns/a
  GET /v1/history/{hostname}/dns/aaaa
  Header: APIKEY: <api_key>
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
PROVIDER = "securitytrails"
_BASE = "https://api.securitytrails.com"
_SUPPORTED_TYPES = {"domain"}
_CACHE_TTL = 86_400  # 24 hours in seconds


def _parse_date(val: str | None) -> datetime | None:
    """Parse ISO date string (YYYY-MM-DD) to UTC datetime or None."""
    if not val:
        return None
    try:
        d = datetime.strptime(val[:10], "%Y-%m-%d")
        return d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


async def _get_cached_pdns(redis, domain: str) -> list[dict] | None:
    key = f"enrich:pdns:securitytrails:{domain}"
    raw = await redis.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def _cache_pdns(redis, domain: str, rows: list[dict]) -> None:
    key = f"enrich:pdns:securitytrails:{domain}"
    # Serialise — convert datetime to isoformat string for JSON
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
    result = []
    for r in raw_rows:
        result.append(
            {
                "ip": r["ip"],
                "first_seen": datetime.fromisoformat(r["first_seen"]) if r["first_seen"] else None,
                "last_seen": datetime.fromisoformat(r["last_seen"]) if r["last_seen"] else None,
                "source": r["source"],
            }
        )
    return result


async def enrich_pdns(
    client: httpx.AsyncClient,
    redis,
    api_key: str | None,
    domain: str,
    project_scope: str,
    daily_cap: int | None = None,
) -> list[dict] | None:
    """Fetch passive DNS A/AAAA history from SecurityTrails.

    Returns list[dict] (may be empty) or None on error/gate.
    Each dict: {"ip": str, "first_seen": datetime|None, "last_seen": datetime|None, "source": str}
    """
    # 1. Circuit breaker
    if await is_breaker_open(redis, PROVIDER, project_scope):
        return None

    # 2. Redis cache (24h)
    cached = await _get_cached_pdns(redis, domain)
    if cached is not None:
        logger.debug("securitytrails_pdns_cache_hit domain=%s", domain)
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

    # 4. Fetch A and AAAA records
    rows: list[dict] = []
    headers = {"APIKEY": api_key or ""}

    for record_type in ("a", "aaaa"):
        url = f"{_BASE}/v1/history/{domain}/dns/{record_type}"
        try:
            response = await client.get(url, headers=headers, timeout=10.0)
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            logger.warning("securitytrails_request_error domain=%s type=%s error=%r",
                           domain, record_type, exc)
            return None

        if response.status_code == 429:
            await record_quota_failure(redis, PROVIDER, project_scope)
            return None
        if response.status_code != 200:
            logger.debug("securitytrails_non200 status=%d domain=%s type=%s",
                         response.status_code, domain, record_type)
            # Non-200 on one type — skip (e.g., AAAA may have no data)
            continue

        for rec in response.json().get("records", []):
            first_seen = _parse_date(rec.get("first_seen"))
            last_seen = _parse_date(rec.get("last_seen"))
            for val in rec.get("values", []):
                ip = val.get("ip")
                if ip:
                    rows.append(
                        {
                            "ip": ip,
                            "first_seen": first_seen,
                            "last_seen": last_seen,
                            "source": PROVIDER,
                        }
                    )

    await _cache_pdns(redis, domain, rows)
    await record_success(redis, PROVIDER, project_scope)
    return rows
