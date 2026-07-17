"""AbuseIPDB enrichment provider — ENRICH-02.

Supports: ip, ipv6

Verdict thresholds (from RESEARCH.md):
  abuseConfidenceScore >= 75 → "malicious"
  abuseConfidenceScore >= 25 → "suspicious"
  else → "clean"

score = abuseConfidenceScore (integer 0-100)
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
PROVIDER = "abuseipdb"
_API_URL = "https://api.abuseipdb.com/api/v2/check"

_SUPPORTED_TYPES = {"ip", "ipv6"}


def _abuse_verdict(score: int) -> str:
    if score >= 75:
        return "malicious"
    if score >= 25:
        return "suspicious"
    return "clean"


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
    """Enrich an IP address using AbuseIPDB.

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

    # 4. Call AbuseIPDB API
    try:
        response = await client.get(
            _API_URL,
            params={"ipAddress": normalized_value, "maxAgeInDays": 90},
            headers={"Key": api_key or "", "Accept": "application/json"},
            timeout=10.0,
        )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.warning("abuseipdb_request_error error=%r", exc)
        return None

    if response.status_code == 429:
        await record_quota_failure(redis, PROVIDER, project_scope)
        return None
    if response.status_code != 200:
        logger.debug("abuseipdb_non200 status=%d", response.status_code)
        return None

    data = response.json()

    # 5. Map verdict
    confidence = data.get("data", {}).get("abuseConfidenceScore", 0)
    verdict = _abuse_verdict(confidence)
    evidence = f"abuseConfidenceScore={confidence}"

    # 6. Cache + record success
    await cache_result(redis, PROVIDER, normalized_value, verdict, float(confidence), evidence)
    await record_success(redis, PROVIDER, project_scope)

    return {
        "provider": PROVIDER,
        "raw_response_jsonb": data,
        "verdict": verdict,
        "score": float(confidence),
        "evidence_text": evidence,
        "fetched_at": datetime.now(timezone.utc),
    }
