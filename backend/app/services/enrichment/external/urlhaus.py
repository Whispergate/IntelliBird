"""URLhaus enrichment provider - ENRICH-02.

Supports: domain, url

URLhaus uses POST with application/x-www-form-urlencoded (NOT GET).
No API key required.

Endpoints:
  url type    → POST https://urlhaus-api.abuse.ch/v1/url/   body: url={encoded}
  domain type → POST https://urlhaus-api.abuse.ch/v1/host/  body: host={domain}

Verdict logic (from RESEARCH.md):
  query_status = "listed" → "malicious"
  else (e.g. "not_listed") → "clean"

score: None (URLhaus does not return a numeric confidence score)
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
PROVIDER = "urlhaus"
_URL_ENDPOINT = "https://urlhaus-api.abuse.ch/v1/url/"
_HOST_ENDPOINT = "https://urlhaus-api.abuse.ch/v1/host/"

_SUPPORTED_TYPES = {"domain", "url"}


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
    """Enrich a URL or domain using URLhaus.

    Uses POST with application/x-www-form-urlencoded. No API key required.
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

    # 4. Build POST body and endpoint
    if ioc_type == "url":
        endpoint = _URL_ENDPOINT
        body = {"url": normalized_value}
    else:  # domain
        endpoint = _HOST_ENDPOINT
        body = {"host": normalized_value}

    # 5. Call URLhaus API (POST, no auth header)
    try:
        response = await client.post(
            endpoint,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10.0,
        )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.warning("urlhaus_request_error ioc_type=%s error=%r", ioc_type, exc)
        return None

    if response.status_code == 429:
        await record_quota_failure(redis, PROVIDER, project_scope)
        return None
    if response.status_code != 200:
        logger.debug("urlhaus_non200 status=%d ioc_type=%s", response.status_code, ioc_type)
        return None

    data = response.json()

    # 6. Map verdict
    query_status = data.get("query_status", "not_listed")
    verdict = "malicious" if query_status == "listed" else "clean"
    evidence = f"query_status={query_status}"

    # 7. Cache + record success
    await cache_result(redis, PROVIDER, normalized_value, verdict, None, evidence)
    await record_success(redis, PROVIDER, project_scope)

    return {
        "provider": PROVIDER,
        "raw_response_jsonb": data,
        "verdict": verdict,
        "score": None,
        "evidence_text": evidence,
        "fetched_at": datetime.now(timezone.utc),
    }
