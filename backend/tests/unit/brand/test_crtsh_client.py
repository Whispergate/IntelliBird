"""Tests for app.services.crtsh_client — async httpx + 429 backoff + name_value parse + dedup.

Activated by plan 12-02 (Wave 2 service primitives).
"""
from __future__ import annotations

import os

# Pydantic-settings singleton bootstrap (see tests/unit/easm for precedent).
os.environ.setdefault("SECRET_KEY", "x" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "y" * 64)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from typing import Any

import httpx
import pytest

from app.services.crtsh_client import (
    BACKOFF_SECONDS,
    _parse_response,
    fetch_certs,
)


# ---------------------------------------------------------------------------
# Helpers — transport that records the requested URL and returns canned responses
# ---------------------------------------------------------------------------


class _QueuedTransport(httpx.AsyncBaseTransport):
    """Replay a queue of (status, payload) tuples; records the last URL."""

    def __init__(self, responses: list[tuple[int, Any]]) -> None:
        self._responses = list(responses)
        self.urls: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        if not self._responses:
            # Exhausted — default to 200 empty
            return httpx.Response(200, json=[])
        status, body = self._responses.pop(0)
        if isinstance(body, (list, dict)):
            return httpx.Response(status, json=body)
        return httpx.Response(status, text=body or "")


async def _fake_sleep_recorder():
    calls: list[float] = []

    async def _sleep(seconds: float) -> None:
        calls.append(seconds)

    return calls, _sleep


# ---------------------------------------------------------------------------
# _parse_response — synchronous unit tests
# ---------------------------------------------------------------------------


def test_parse_name_value_splits_on_newline():
    rows = [{"name_value": "a.x.io\nb.x.io", "not_before": "2026-01-01T00:00:00"}]
    out = _parse_response(rows)
    values = sorted(e["matched_value"] for e in out)
    assert values == ["a.x.io", "b.x.io"]


def test_parse_strips_wildcard_prefix():
    rows = [{"name_value": "*.x.io", "not_before": "2026-01-01T00:00:00"}]
    out = _parse_response(rows)
    assert len(out) == 1
    assert out[0]["matched_value"] == "x.io"


def test_parse_lowercases_san():
    rows = [{"name_value": "FOO.X.IO", "not_before": "2026-01-01T00:00:00"}]
    out = _parse_response(rows)
    assert out[0]["matched_value"] == "foo.x.io"


def test_dedup_precert_and_cert_via_san_not_before():
    # Two rows (precert + cert) with same san and same not_before → collapse
    rows = [
        {"name_value": "dup.x.io", "not_before": "2026-01-01T00:00:00", "min_cert_id": 1},
        {"name_value": "dup.x.io", "not_before": "2026-01-01T00:00:00", "min_cert_id": 2},
    ]
    out = _parse_response(rows)
    assert len(out) == 1


def test_parse_empty_name_value_skipped():
    rows = [{"name_value": "\n\n", "not_before": "2026-01-01T00:00:00"}]
    out = _parse_response(rows)
    assert out == []


def test_parse_preserves_issuer_fields():
    rows = [{
        "name_value": "x.io",
        "not_before": "2026-01-01T00:00:00",
        "not_after": "2026-12-31T00:00:00",
        "issuer_ca_id": 1234,
        "issuer_name": "Let's Encrypt",
        "min_cert_id": 99,
    }]
    out = _parse_response(rows)
    assert out[0]["issuer_ca_id"] == 1234
    assert out[0]["issuer_name"] == "Let's Encrypt"
    assert out[0]["not_after"] == "2026-12-31T00:00:00"
    assert out[0]["min_cert_id"] == 99


# ---------------------------------------------------------------------------
# fetch_certs — async integration-lite via httpx MockTransport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_certs_uses_wildcard_query():
    transport = _QueuedTransport([(200, [])])
    async with httpx.AsyncClient(transport=transport) as client:
        calls, sleep = await _fake_sleep_recorder()
        await fetch_certs("intellibird.io", sleep=sleep, client=client)
    assert len(transport.urls) == 1
    # URL contains the wildcard query — %25 is URL-encoded '%'
    assert "q=%25.intellibird.io" in transport.urls[0]
    assert "output=json" in transport.urls[0]


@pytest.mark.asyncio
async def test_fetch_certs_returns_parsed_rows_on_200():
    payload = [{"name_value": "a.x.io", "not_before": "2026-01-01T00:00:00"}]
    transport = _QueuedTransport([(200, payload)])
    async with httpx.AsyncClient(transport=transport) as client:
        calls, sleep = await _fake_sleep_recorder()
        result = await fetch_certs("x.io", sleep=sleep, client=client)
    assert len(result) == 1
    assert result[0]["matched_value"] == "a.x.io"


@pytest.mark.asyncio
async def test_429_backoff_sequence_30_60_120():
    # Three 429 responses → three backoff sleeps (30, 60, 120) then returns [].
    transport = _QueuedTransport([(429, ""), (429, ""), (429, "")])
    async with httpx.AsyncClient(transport=transport) as client:
        calls, sleep = await _fake_sleep_recorder()
        result = await fetch_certs("x.io", sleep=sleep, client=client)
    assert calls == list(BACKOFF_SECONDS) == [30, 60, 120]
    assert result == []


@pytest.mark.asyncio
async def test_429_recovers_on_200():
    # One 429, then a 200 with parsed rows → returns parsed certs after one 30s sleep.
    payload = [{"name_value": "ok.x.io", "not_before": "2026-01-01T00:00:00"}]
    transport = _QueuedTransport([(429, ""), (200, payload)])
    async with httpx.AsyncClient(transport=transport) as client:
        calls, sleep = await _fake_sleep_recorder()
        result = await fetch_certs("x.io", sleep=sleep, client=client)
    assert calls == [30]
    assert len(result) == 1
    assert result[0]["matched_value"] == "ok.x.io"


@pytest.mark.asyncio
async def test_5xx_returns_empty_skips_cycle():
    transport = _QueuedTransport([(500, "")])
    async with httpx.AsyncClient(transport=transport) as client:
        calls, sleep = await _fake_sleep_recorder()
        result = await fetch_certs("x.io", sleep=sleep, client=client)
    assert result == []
    # No backoff sleeps — 5xx is a skip-cycle, not a retry.
    assert calls == []


@pytest.mark.asyncio
async def test_non_200_non_5xx_returns_empty():
    # e.g. 404 — not a rate limit, not a server error, just no data.
    transport = _QueuedTransport([(404, "")])
    async with httpx.AsyncClient(transport=transport) as client:
        calls, sleep = await _fake_sleep_recorder()
        result = await fetch_certs("x.io", sleep=sleep, client=client)
    assert result == []


@pytest.mark.asyncio
async def test_malformed_json_returns_empty():
    transport = _QueuedTransport([(200, "not-json-at-all")])
    async with httpx.AsyncClient(transport=transport) as client:
        calls, sleep = await _fake_sleep_recorder()
        result = await fetch_certs("x.io", sleep=sleep, client=client)
    assert result == []
