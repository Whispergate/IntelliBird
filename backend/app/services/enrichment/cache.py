"""Enrichment result Redis cache — Phase 23 / ENRICH-03.

24-hour per-provider, per-indicator result cache. Cache hits bypass the
quota gate entirely — a cache hit never increments any quota counter.

Redis key shape:
  enrich:result:{provider}:{normalized_indicator}   TTL=86400s (24h)

SET NX (EX/PX) is used so a concurrent write from another worker does
not overwrite an existing entry.

Public API:
  get_cached_result(redis, provider, normalized_indicator) -> dict | None
  cache_result(redis, provider, normalized_indicator, verdict, score, evidence_text)
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_CACHE_TTL_MS: int = 86_400_000  # 24 hours in milliseconds


def _cache_key(provider: str, normalized_indicator: str) -> str:
    return f"enrich:result:{provider}:{normalized_indicator}"


async def get_cached_result(
    redis,
    provider: str,
    normalized_indicator: str,
) -> dict | None:
    """Return cached enrichment payload or None on cache miss.

    The returned dict has keys: verdict, score, evidence_text.
    """
    key = _cache_key(provider, normalized_indicator)
    raw = await redis.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "enrich_cache_decode_error provider=%s indicator=%s",
            provider,
            normalized_indicator,
        )
        return None


async def cache_result(
    redis,
    provider: str,
    normalized_indicator: str,
    verdict: str,
    score: float | None,
    evidence_text: str | None,
) -> None:
    """Store enrichment result in Redis with NX semantics (no overwrite).

    Uses SET key value PX 86400000 NX so concurrent workers writing
    the same key do not overwrite the first writer's result.
    """
    key = _cache_key(provider, normalized_indicator)
    payload = json.dumps(
        {"verdict": verdict, "score": score, "evidence_text": evidence_text},
        separators=(",", ":"),
    )
    # NX=True → only set if key does not exist
    await redis.set(key, payload, px=_CACHE_TTL_MS, nx=True)


__all__ = ["get_cached_result", "cache_result"]
