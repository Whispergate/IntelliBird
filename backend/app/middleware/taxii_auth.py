"""TAXII 2.1 partner-key authentication dependency — Phase 26 / TAXII-03.

IMPORTANT: This is NOT an ASGI middleware — it is a FastAPI Depends() dependency.
It does NOT extend AuthMiddleware or touch JWTs. The TAXII router prefix (/taxii2)
must be exempt from AuthMiddleware (done in plan 26-04 / main.py).

Auth options accepted (TAXII 2.1 §3.3 SHOULD):
  - Authorization: Basic base64(<anything>:<raw_api_key>)  — password field is the key
  - X-TAXII-API-Key: <raw_api_key>  — custom header (widely supported by TAXII clients)

Key lookup: SHA-256 hex digest of raw key -> SELECT FROM taxii_clients WHERE api_key_hash = ?
  - NO CACHING. Revocation must be effective within one request (TAXII-03).
  - taxii_clients is tiny (tens of rows) — direct DB lookup is sub-millisecond.

Rate limiting: Redis sorted-set rolling window (60-second window, per client ID).
  - Key pattern: taxii:ratelimit:{client_id}
  - Raises HTTP 429 when count exceeds client.rate_limit_rpm.
  - Redis failure is FAIL-OPEN for rate limiting only (TAXII-03 is about key revocation,
    not rate limiting). Log a warning and allow through if Redis is down.
"""
from __future__ import annotations

import base64
import hashlib
import time

import structlog
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.taxii import TaxiiClient
from app.services.redis_client import get_redis

log = structlog.get_logger(__name__)


def _extract_raw_key(request: Request) -> str | None:
    """Extract raw API key from request headers.

    Checks:
    1. X-TAXII-API-Key: <key>
    2. Authorization: Basic base64(<client_id>:<key>)  — password field used as key
    """
    # Custom header (takes priority — simpler for automated clients)
    header_key = request.headers.get("X-TAXII-API-Key")
    if header_key:
        return header_key.strip()

    # HTTP Basic — password field is the API key
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8", errors="replace")
            # Format is "username:password" — password is the key
            _, _, raw_key = decoded.partition(":")
            if raw_key:
                return raw_key.strip()
        except Exception:
            pass

    return None


def _hash_key(raw_key: str) -> str:
    """Return SHA-256 hex digest of raw API key."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


async def _check_rate_limit(client: TaxiiClient) -> None:
    """Redis rolling-window rate limiter — raises HTTP 429 if exceeded.

    Uses a sorted set with UNIX timestamp scores. Window = 60 seconds.
    Limit = client.rate_limit_rpm (requests per minute).
    FAIL-OPEN: if Redis is unavailable, log warning and allow request through.
    """
    redis = None
    try:
        redis = await get_redis()
        key = f"taxii:ratelimit:{client.id}"
        now = time.time()
        window_start = now - 60.0
        pipe = redis.pipeline()
        # Remove entries older than 60s
        pipe.zremrangebyscore(key, "-inf", window_start)
        # Add current request
        pipe.zadd(key, {str(now): now})
        # Count requests in window
        pipe.zcount(key, window_start, "+inf")
        # Expire the key after 120s (2x window to handle clock skew)
        pipe.expire(key, 120)
        results = await pipe.execute()
        count = results[2]
        if count > client.rate_limit_rpm:
            log.warning(
                "taxii_rate_limit_exceeded",
                client_id=str(client.id),
                label=client.label,
                count=count,
                limit=client.rate_limit_rpm,
            )
            raise HTTPException(
                status_code=429,
                detail="taxii_rate_limit_exceeded",
                headers={"Retry-After": "60"},
            )
    except HTTPException:
        raise
    except Exception:
        log.warning("taxii_rate_limit_redis_unavailable", client_id=str(client.id))
        # FAIL-OPEN: allow request through if Redis is down


async def require_taxii_client(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TaxiiClient:
    """FastAPI dependency that authenticates a TAXII partner request.

    Returns the TaxiiClient ORM row on success.
    Raises HTTP 401 for missing/invalid/revoked keys.
    Raises HTTP 429 for rate-limit exceeded.

    NEVER caches lookups — revocation must be instantaneous (TAXII-03).
    """
    raw_key = _extract_raw_key(request)
    if not raw_key:
        raise HTTPException(
            status_code=401,
            detail="taxii_auth_required",
            headers={"WWW-Authenticate": 'Basic realm="taxii"'},
        )

    key_hash = _hash_key(raw_key)

    # Direct DB lookup — no cache (TAXII-03: revocation must be instant)
    result = await session.execute(
        select(TaxiiClient).where(TaxiiClient.api_key_hash == key_hash)
    )
    client = result.scalar_one_or_none()

    if client is None:
        log.info("taxii_auth_key_not_found", key_hash_prefix=key_hash[:8])
        raise HTTPException(
            status_code=401,
            detail="taxii_invalid_key",
            headers={"WWW-Authenticate": 'Basic realm="taxii"'},
        )

    if client.revoked:
        log.info("taxii_auth_key_revoked", client_id=str(client.id), label=client.label)
        raise HTTPException(
            status_code=401,
            detail="taxii_key_revoked",
            headers={"WWW-Authenticate": 'Basic realm="taxii"'},
        )

    await _check_rate_limit(client)

    return client


__all__ = ["require_taxii_client"]
