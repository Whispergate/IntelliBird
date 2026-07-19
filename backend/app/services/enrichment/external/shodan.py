"""Shodan enrichment provider - ENRICH-02.

Supports: ip, ipv6

Endpoint: GET https://api.shodan.io/shodan/host/{ip}?key={api_key}

Verdict thresholds (from RESEARCH.md):
  0 vulns  → "unknown"
  1-3 vulns → "suspicious"
  > 3 vulns → "malicious"

score = min(float(vuln_count * 10), 100.0)
evidence_text = first 5 CVE keys joined by ", "

CRITICAL: HTTP 401 (free-tier key insufficient for host lookups) must NOT
call record_quota_failure - it is a permanent API key limitation, not a
transient quota event. Return None with evidence_text="shodan_key_insufficient".
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
PROVIDER = "shodan"
_BASE = "https://api.shodan.io"

_SUPPORTED_TYPES = {"ip", "ipv6"}


def _shodan_verdict(vulns: dict) -> tuple[str, float, str]:
    """Map Shodan vuln dict to (verdict, score, evidence_text)."""
    vuln_count = len(vulns)
    cves = ", ".join(list(vulns.keys())[:5])

    if vuln_count == 0:
        return "unknown", 0.0, "no_vulns"
    if vuln_count <= 3:
        return "suspicious", min(float(vuln_count * 10), 100.0), cves
    return "malicious", min(float(vuln_count * 10), 100.0), cves


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
    """Enrich an IP address using Shodan host lookup.

    Returns a dict ready for IOCEnrichment creation, or None on failure.

    HTTP 401 → None (key insufficient - NOT a quota failure, do not call
    record_quota_failure).
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

    # 4. Call Shodan API
    try:
        response = await client.get(
            f"{_BASE}/shodan/host/{normalized_value}",
            params={"key": api_key or ""},
            timeout=10.0,
        )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.warning("shodan_request_error error=%r", exc)
        return None

    if response.status_code == 401:
        # Free-tier API key cannot perform host lookups - NOT a quota failure
        logger.info("shodan_key_insufficient ip=%s", normalized_value)
        return {
            "provider": PROVIDER,
            "raw_response_jsonb": None,
            "verdict": "unknown",
            "score": None,
            "evidence_text": "shodan_key_insufficient",
            "fetched_at": datetime.now(timezone.utc),
        }

    if response.status_code == 404:
        # IP not indexed in Shodan - valid "unknown"
        await record_success(redis, PROVIDER, project_scope)
        verdict, score, evidence = "unknown", 0.0, "ip_not_in_shodan"
        await cache_result(redis, PROVIDER, normalized_value, verdict, score, evidence)
        return {
            "provider": PROVIDER,
            "raw_response_jsonb": None,
            "verdict": verdict,
            "score": score,
            "evidence_text": evidence,
            "fetched_at": datetime.now(timezone.utc),
        }

    if response.status_code == 429:
        await record_quota_failure(redis, PROVIDER, project_scope)
        return None
    if response.status_code != 200:
        logger.debug("shodan_non200 status=%d", response.status_code)
        return None

    data = response.json()

    # 5. Map verdict
    vulns = data.get("vulns", {}) or {}
    verdict, score, evidence = _shodan_verdict(vulns)

    # 6. Cache + record success
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
