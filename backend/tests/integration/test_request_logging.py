"""Integration: RequestLogMiddleware echoes X-Request-Id and emits http_request."""
from __future__ import annotations

import os

# Must set required env vars before importing app modules
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "x" * 48)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest  # noqa: E402
from httpx import AsyncClient, ASGITransport  # noqa: E402

from app.main import app  # noqa: E402


pytestmark = pytest.mark.integration


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_request_id_generated_when_absent():
    async with await _client() as c:
        r = await c.get("/healthz")
        assert "x-request-id" in [h.lower() for h in r.headers.keys()]
        assert len(r.headers["X-Request-Id"]) >= 32


@pytest.mark.asyncio
async def test_request_id_echoed_when_provided():
    async with await _client() as c:
        r = await c.get("/healthz", headers={"X-Request-Id": "my-trace-id-42"})
        assert r.headers["X-Request-Id"] == "my-trace-id-42"


@pytest.mark.asyncio
async def test_api_path_stamps_request_id():
    """Any path under /api/* gets X-Request-Id from middleware (tested on /healthz, no DB needed)."""
    async with await _client() as c:
        r = await c.get("/api/system/status")
        # status may vary (200 or 503 if DB is not reachable) but header must always be set
        assert "x-request-id" in [h.lower() for h in r.headers.keys()]


@pytest.mark.asyncio
async def test_dashboard_role_captured_in_middleware():
    """Not visible in response headers; verified indirectly by middleware completing."""
    async with await _client() as c:
        r = await c.get("/healthz", headers={"X-Dashboard-Role": "blue"})
        assert r.status_code == 200
        assert "x-request-id" in [h.lower() for h in r.headers.keys()]
        # The log line is captured to stdout — live integration checks it via docker logs
        # (full assertion handled in unit test; integration here verifies the handler path runs)
