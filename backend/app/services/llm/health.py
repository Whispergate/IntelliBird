"""Ollama startup health probe — AI-05.

Public API:
  probe_ollama(base_url, timeout) -> HealthStatus
  get_ollama_health(app) -> HealthStatus

The probe is called during FastAPI lifespan startup and stores the result
on app.state.ollama_health.  Non-blocking: if Ollama is down, startup
continues and the health endpoint surfaces "down".

HealthStatus values:
  "healthy" — HTTP 200 received in < 5 s
  "slow"    — HTTP 200 received but elapsed >= 5 s (probe timeout is 10 s)
  "down"    — non-200 response, connection error, or timeout
  "unknown" — probe has not yet run (initial state)
"""
from __future__ import annotations

import time
from typing import Literal

import httpx

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

HealthStatus = Literal["healthy", "slow", "down", "unknown"]

_SLOW_THRESHOLD_S: float = 5.0

# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


async def probe_ollama(
    base_url: str,
    timeout: float = 10.0,
) -> HealthStatus:
    """GET /api/tags from the Ollama service and classify the response.

    Args:
        base_url: Ollama base URL, e.g. "http://ollama:11434".
        timeout:  Request timeout in seconds (default 10 s per CONTEXT.md).

    Returns:
        "healthy" if 200 and elapsed < 5 s,
        "slow"    if 200 and elapsed >= 5 s,
        "down"    on non-200, connection error, or timeout.
    """
    url = f"{base_url.rstrip('/')}/api/tags"
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=timeout)
        elapsed = time.monotonic() - t0
        if r.status_code == 200:
            return "slow" if elapsed >= _SLOW_THRESHOLD_S else "healthy"
        return "down"
    except Exception:
        return "down"


# ---------------------------------------------------------------------------
# App state accessor
# ---------------------------------------------------------------------------


def get_ollama_health(app) -> HealthStatus:
    """Return the stored Ollama health status from app.state.

    Returns "unknown" if the probe has not been run yet (e.g. during testing
    or if the lifespan hook was not attached).
    """
    return getattr(app.state, "ollama_health", "unknown")
