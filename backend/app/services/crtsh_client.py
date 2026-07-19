"""crt.sh polling client.

Async httpx GET against https://crt.sh/?q=%.{term}&output=json with:
- 429 rate-limit backoff: 30s, 60s, 120s, then skip cycle (return []).
- 5xx / network error: return [] immediately (skip cycle, not retry).
- name_value newline-splitting, wildcard prefix strip, precert/cert dedup
  via (san, not_before) key - matches the plan 12-02 must-have truths.

Returns a list of normalised dicts:
    {
        "matched_value": "a.x.io",         # lowercased SAN, wildcard stripped
        "not_before": "2026-01-01T00:00:00",
        "not_after":  "2026-12-31T00:00:00",
        "issuer_ca_id": 1234,
        "issuer_name": "Let's Encrypt",
        "min_cert_id": 99,
    }
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Iterable

import httpx

log = logging.getLogger(__name__)

# Backoff sequence for 429 responses (seconds). Three attempts total.
BACKOFF_SECONDS: tuple[int, ...] = (30, 60, 120)

REQUEST_TIMEOUT: float = 30.0

SleepFn = Callable[[float], Awaitable[None]]


async def fetch_certs(
    term_value: str,
    *,
    sleep: SleepFn = asyncio.sleep,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Poll crt.sh for SANs matching %.{term_value}.

    Returns a deduplicated list of cert-record dicts. Returns [] on persistent
    429, 5xx, network error, or malformed JSON - caller interprets [] as
    "skip this cycle, try again next tick".
    """
    # Use params= so httpx URL-encodes the '%' wildcard prefix (→ %25) - matches
    # what crt.sh accepts and what tests assert.
    url = "https://crt.sh/"
    params = {"q": f"%.{term_value}", "output": "json"}
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
    try:
        for attempt, backoff in enumerate(BACKOFF_SECONDS):
            try:
                resp = await client.get(url, params=params)
            except httpx.RequestError as exc:
                log.warning(
                    "crtsh_request_error",
                    extra={"term": term_value, "exc": str(exc)},
                )
                return []

            status = resp.status_code
            if status == 429:
                log.warning(
                    "crtsh_rate_limited",
                    extra={"term": term_value, "attempt": attempt, "backoff": backoff},
                )
                await sleep(backoff)
                continue
            if 500 <= status < 600:
                log.warning(
                    "crtsh_server_error",
                    extra={"term": term_value, "status": status},
                )
                return []
            if status != 200:
                return []

            try:
                data = resp.json()
            except Exception:
                log.warning("crtsh_malformed_json", extra={"term": term_value})
                return []
            return _parse_response(data)

        log.warning("crtsh_persistent_429_skipping_cycle", extra={"term": term_value})
        return []
    finally:
        if owns_client:
            await client.aclose()


def _parse_response(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse a crt.sh JSON response.

    - Splits name_value on newlines (each row can carry multiple SANs).
    - lstrip('*.') to collapse wildcard-certs with their base SAN.
    - Dedups precert + cert pairs via (san, not_before) tuple.
    - Lowercases SAN for consistent downstream comparison.
    """
    seen: dict[tuple[str, str | None], dict[str, Any]] = {}
    for row in rows:
        name_value = row.get("name_value", "") or ""
        not_before = row.get("not_before")
        for raw_san in name_value.split("\n"):
            # lstrip('*.') would also eat legitimate leading dots/asterisks in
            # weird edge cases, but name_value values are SANs so this is safe.
            san = raw_san.strip().lstrip("*.").strip().lower()
            if not san:
                continue
            key = (san, not_before)
            if key in seen:
                continue
            seen[key] = {
                "matched_value": san,
                "not_before": not_before,
                "not_after": row.get("not_after"),
                "issuer_ca_id": row.get("issuer_ca_id"),
                "issuer_name": row.get("issuer_name"),
                "min_cert_id": row.get("min_cert_id"),
            }
    return list(seen.values())
