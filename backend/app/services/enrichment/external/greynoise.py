"""GreyNoise enrichment provider — Phase 23 / ENRICH-02.

Supports: ip, ipv6

Community tier endpoint: GET /v3/community/{ip}
api_key=None is valid (community tier — no auth header sent).

Verdict logic (from RESEARCH.md):
  HTTP 404 → "unknown" (IP not seen)
  riot=True → "clean" (legitimate internet scanner)
  noise=False → "unknown"
  classification="malicious" → "malicious"
  noise=True + other classification → "suspicious"

score: None (community tier does not return a numeric score)

IMPORTANT: Wrap field access in try/except KeyError per RESEARCH.md
(API shape stability risk — fields may be absent in some responses).
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
PROVIDER = "greynoise"
_BASE = "https://api.greynoise.io"

_SUPPORTED_TYPES = {"ip", "ipv6"}


def _gn_verdict(data: dict) -> tuple[str, str]:
    """Map GreyNoise community response to (verdict, evidence_text).

    Returns ("unknown", <reason>) on missing or unexpected fields.
    """
    try:
        riot = data.get("riot", False)
        noise = data.get("noise", False)
        classification = data.get("classification", "")

        if riot:
            return "clean", "riot=true"
        if not noise:
            return "unknown", "noise=false"
        if classification == "malicious":
            return "malicious", f"classification={classification}"
        return "suspicious", f"noise=true classification={classification or 'benign'}"
    except KeyError as exc:
        logger.debug("greynoise_field_missing field=%r", exc)
        return "unknown", "unexpected_response_shape"


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
    """Enrich an IP address using GreyNoise community API.

    api_key=None is valid (community tier, no auth header required).
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

    # 4. Build headers — only include key header when api_key is provided
    headers: dict[str, str] = {}
    if api_key:
        headers["key"] = api_key

    # 5. Call GreyNoise API
    try:
        response = await client.get(
            f"{_BASE}/v3/community/{normalized_value}",
            headers=headers,
            timeout=10.0,
        )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.warning("greynoise_request_error error=%r", exc)
        return None

    if response.status_code == 404:
        # IP not observed in GreyNoise — not an error, valid "unknown"
        await record_success(redis, PROVIDER, project_scope)
        verdict, evidence = "unknown", "ip_not_seen"
        await cache_result(redis, PROVIDER, normalized_value, verdict, None, evidence)
        return {
            "provider": PROVIDER,
            "raw_response_jsonb": None,
            "verdict": verdict,
            "score": None,
            "evidence_text": evidence,
            "fetched_at": datetime.now(timezone.utc),
        }

    if response.status_code == 429:
        await record_quota_failure(redis, PROVIDER, project_scope)
        return None
    if response.status_code != 200:
        logger.debug("greynoise_non200 status=%d", response.status_code)
        return None

    data = response.json()

    # 6. Map verdict
    verdict, evidence = _gn_verdict(data)

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
