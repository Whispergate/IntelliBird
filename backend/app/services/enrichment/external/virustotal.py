"""VirusTotal enrichment provider — Phase 23 / ENRICH-02.

Supports: ip, ipv6, domain, url, sha256, sha1, md5

Verdict thresholds (from RESEARCH.md):
  malicious >= 5 detections → "malicious"
  suspicious >= 5 detections (and < 5 malicious) → "suspicious"
  0 total scans → "unknown"
  else → "clean"

score = round((malicious / total) * 100, 2) when total > 0
"""
from __future__ import annotations

import base64
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
PROVIDER = "vt"
_BASE = "https://www.virustotal.com"

_SUPPORTED_TYPES = {"ip", "ipv6", "domain", "url", "sha256", "sha1", "md5"}


def _vt_url(ioc_type: str, value: str) -> str:
    """Build VirusTotal v3 API URL for the given IOC type."""
    if ioc_type in ("ip", "ipv6"):
        return f"{_BASE}/api/v3/ip_addresses/{value}"
    if ioc_type == "domain":
        return f"{_BASE}/api/v3/domains/{value}"
    if ioc_type == "url":
        # VT expects base64url-encoded URL (no padding)
        encoded = base64.urlsafe_b64encode(value.encode()).rstrip(b"=").decode()
        return f"{_BASE}/api/v3/urls/{encoded}"
    # sha256, sha1, md5
    return f"{_BASE}/api/v3/files/{value}"


def _vt_verdict(stats: dict) -> tuple[str, float | None]:
    """Map VT last_analysis_stats to (verdict, score)."""
    malicious = stats.get("malicious", 0)
    suspicious = stats.get("suspicious", 0)
    total = sum(stats.values()) if stats else 0

    if total == 0:
        return "unknown", None
    if malicious >= 5:
        return "malicious", round((malicious / total) * 100, 2)
    if suspicious >= 5:
        return "suspicious", round((suspicious / total) * 100, 2)
    if malicious > 0:
        return "suspicious", round((malicious / total) * 100, 2)
    return "clean", 0.0


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
    """Enrich an IOC using VirusTotal v3 API.

    Returns a dict ready for IOCEnrichment creation, or None when:
      - IOC type not supported by VT
      - Circuit breaker open
      - Quota exceeded (minute or day)
      - API call fails (timeout, non-200 response)
    """
    if ioc_type not in _SUPPORTED_TYPES:
        return None

    # 1. Check circuit breaker
    if await is_breaker_open(redis, PROVIDER, project_scope):
        return None

    # 2. Check cache BEFORE quota (cache hit costs zero quota)
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

    # 4. Call VirusTotal API
    try:
        response = await client.get(
            _vt_url(ioc_type, normalized_value),
            headers={"x-apikey": api_key or ""},
            timeout=10.0,
        )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.warning("vt_request_error ioc_type=%s error=%r", ioc_type, exc)
        return None

    if response.status_code == 429:
        await record_quota_failure(redis, PROVIDER, project_scope)
        return None
    if response.status_code != 200:
        logger.debug("vt_non200 status=%d ioc_type=%s", response.status_code, ioc_type)
        return None

    data = response.json()

    # 5. Map verdict
    stats = data.get("data", {}).get("attributes", {}).get("last_analysis_stats", {})
    verdict, score = _vt_verdict(stats)
    evidence = (
        f"malicious={stats.get('malicious', 0)} suspicious={stats.get('suspicious', 0)}"
    )

    # 6. Cache result + record success
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
