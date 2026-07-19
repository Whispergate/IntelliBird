"""RiskIQ Community / PassiveTotal passive DNS provider - ENRICH-06.

Supports: domain

Returns list[dict] | None where each dict:
  {"ip": str, "first_seen": datetime|None, "last_seen": datetime|None, "source": str}

API docs: https://api.passivetotal.org/index.html
  GET /v2/dns/passive?query={domain}
  Auth: HTTP Basic - username + api_secret from JSON credentials string

Credentials format (stored encrypted in EnrichmentProvider.credentials_enc):
  '{"username": "user@example.com", "api_secret": "abc123..."}'
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
PROVIDER = "riskiq_community"
_BASE = "https://api.passivetotal.org"
_SUPPORTED_TYPES = {"domain"}
_CACHE_TTL = 86_400  # 24 hours in seconds


def _parse_datetime(val: str | None) -> datetime | None:
    """Parse RiskIQ datetime string '%Y-%m-%d %H:%M:%S' to UTC datetime."""
    if not val:
        return None
    try:
        return datetime.strptime(val, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


async def _get_cached_pdns(redis, domain: str) -> list[dict] | None:
    key = f"enrich:pdns:riskiq:{domain}"
    raw = await redis.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def _cache_pdns(redis, domain: str, rows: list[dict]) -> None:
    key = f"enrich:pdns:riskiq:{domain}"
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
    """Fetch passive DNS records from RiskIQ Community / PassiveTotal.

    api_key must be a JSON string: '{"username":"...","api_secret":"..."}'
    Returns list[dict] (may be empty) or None on error/gate.
    Each dict: {"ip": str, "first_seen": datetime|None, "last_seen": datetime|None, "source": str}
    """
    # 1. Circuit breaker
    if await is_breaker_open(redis, PROVIDER, project_scope):
        return None

    # 2. Redis cache (24h)
    cached = await _get_cached_pdns(redis, domain)
    if cached is not None:
        logger.debug("riskiq_pdns_cache_hit domain=%s", domain)
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

    # 4. Parse JSON credentials string for HTTP Basic auth
    creds = json.loads(api_key or "{}")
    username = creds.get("username", "")
    secret = creds.get("api_secret", "")

    # 5. API call
    url = f"{_BASE}/v2/dns/passive"
    try:
        response = await client.get(
            url,
            params={"query": domain},
            auth=(username, secret),
            timeout=10.0,
        )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.warning("riskiq_request_error domain=%s error=%r", domain, exc)
        return None

    if response.status_code == 429:
        await record_quota_failure(redis, PROVIDER, project_scope)
        return None
    if response.status_code != 200:
        logger.debug("riskiq_non200 status=%d domain=%s", response.status_code, domain)
        return None

    rows: list[dict] = []
    for rec in response.json().get("results", []):
        if rec.get("resolveType") != "ip":
            continue
        rows.append(
            {
                "ip": rec["resolve"],
                "first_seen": _parse_datetime(rec.get("firstSeen")),
                "last_seen": _parse_datetime(rec.get("lastSeen")),
                "source": PROVIDER,
            }
        )

    await _cache_pdns(redis, domain, rows)
    await record_success(redis, PROVIDER, project_scope)
    return rows
