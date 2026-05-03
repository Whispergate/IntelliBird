"""OTX (AlienVault Open Threat Exchange) enrichment provider — Phase 23 / ENRICH-02.

Supports: domain, sha256, sha1, md5
(ip/ipv6 intentionally not included — see PROVIDER_IOC_ROUTING in resolver.py)

Endpoint: GET https://otx.alienvault.com/api/v1/indicators/{otx_type}/{value}/general

OTX type mapping:
  ip   → IPv4      (not used here; OTX routing excludes ip)
  ipv6 → IPv6      (not used here)
  domain → domain
  sha256/sha1/md5 → file

Verdict thresholds (from RESEARCH.md):
  0 pulses  → "clean"
  1-9 pulses → "suspicious"
  >= 10 pulses → "malicious"

score = min(pulse_count * 10, 100.0)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.services.enrichment.cache import get_cached_result, cache_result
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
PROVIDER = "otx"
_BASE = "https://otx.alienvault.com"

_SUPPORTED_TYPES = {"domain", "sha256", "sha1", "md5"}

_OTX_TYPE_MAP = {
    "ip": "IPv4",
    "ipv6": "IPv6",
    "domain": "domain",
    "sha256": "file",
    "sha1": "file",
    "md5": "file",
}


def _otx_verdict(pulse_count: int) -> tuple[str, float]:
    """Map OTX pulse count to (verdict, score)."""
    if pulse_count == 0:
        return "clean", 0.0
    if pulse_count >= 10:
        return "malicious", min(pulse_count * 10.0, 100.0)
    return "suspicious", min(pulse_count * 10.0, 100.0)


async def enrich(
    client: httpx.AsyncClient,
    redis,
    api_key: str | None,
    ioc_type: str,
    normalized_value: str,
    project_scope: str,
    daily_cap: int | None = None,
    force_refresh: bool = False,
) -> dict | None:
    """Enrich an IOC using OTX AlienVault.

    Returns a dict ready for IOCEnrichment creation, or None on failure.
    """
    if ioc_type not in _SUPPORTED_TYPES:
        return None

    # 1. Check circuit breaker
    if await is_breaker_open(redis, PROVIDER, project_scope):
        return None

    # 2. Check cache BEFORE quota
    if not force_refresh:
        cached = await get_cached_result(redis, PROVIDER, normalized_value)
        if cached:
            return {
                "provider": PROVIDER,
                "raw_response_jsonb": None,
                "verdict": cached["verdict"],
                "score": cached["score"],
                "evidence_text": cached["evidence_text"],
                "fetched_at": datetime.now(timezone.utc),
            }

    # 3. Check quota
    cap = daily_cap if daily_cap is not None else PROVIDER_DEFAULT_DAILY_CAPS[PROVIDER]
    allowed = await check_and_consume_quota(
        redis, PROVIDER, project_scope,
        minute_cap=PROVIDER_MINUTE_CAPS[PROVIDER],
        daily_cap=cap,
    )
    if not allowed:
        return None

    # 4. Build URL
    otx_type = _OTX_TYPE_MAP.get(ioc_type, ioc_type)
    url = f"{_BASE}/api/v1/indicators/{otx_type}/{normalized_value}/general"

    # 5. Call OTX API
    try:
        response = await client.get(
            url,
            headers={"X-OTX-API-KEY": api_key or ""},
            timeout=10.0,
        )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.warning("otx_request_error ioc_type=%s error=%r", ioc_type, exc)
        return None

    if response.status_code == 429:
        await record_quota_failure(redis, PROVIDER, project_scope)
        return None
    if response.status_code != 200:
        logger.debug("otx_non200 status=%d ioc_type=%s", response.status_code, ioc_type)
        return None

    data = response.json()

    # 6. Map verdict
    pulse_count = data.get("pulse_info", {}).get("count", 0)
    verdict, score = _otx_verdict(pulse_count)
    evidence = f"pulse_count={pulse_count}"

    # 7. Cache + record success
    await cache_result(redis, PROVIDER, normalized_value, verdict, score, evidence)
    await record_success(redis, PROVIDER, project_scope)

    return {
        "provider": PROVIDER,
        "raw_response_jsonb": data,
        "verdict": verdict,
        "score": score,
        "evidence_text": evidence,
        "fetched_at": datetime.now(timezone.utc),
    }
