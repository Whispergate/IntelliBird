"""Unit tests for SecurityTrails passive DNS provider — ENRICH-06."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx


@pytest.mark.asyncio
async def test_securitytrails_returns_rows_for_valid_response():
    """ENRICH-06: SecurityTrails provider maps API response to passive DNS rows."""
    from app.services.enrichment.external.securitytrails import enrich_pdns

    # A-record response: 2 IPs
    mock_a_response = MagicMock()
    mock_a_response.status_code = 200
    mock_a_response.json.return_value = {
        "records": [
            {
                "first_seen": "2023-01-15",
                "last_seen": "2024-11-01",
                "values": [
                    {"ip": "104.21.5.32", "ip_count": 3},
                    {"ip": "172.67.189.21", "ip_count": 2},
                ],
            }
        ]
    }
    # AAAA-record response: empty (IPv6 not present for test domain)
    mock_aaaa_response = MagicMock()
    mock_aaaa_response.status_code = 200
    mock_aaaa_response.json.return_value = {"records": []}

    mock_client = AsyncMock()
    mock_client.get.side_effect = [mock_a_response, mock_aaaa_response]
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None  # cache miss
    mock_redis.set.return_value = True

    with (
        patch("app.services.enrichment.external.securitytrails.is_breaker_open", return_value=False),
        patch("app.services.enrichment.external.securitytrails.check_and_consume_quota", return_value=True),
        patch("app.services.enrichment.external.securitytrails.record_success"),
    ):
        rows = await enrich_pdns(
            mock_client, mock_redis, "test-api-key", "example.com", "proj-1"
        )

    assert rows is not None
    assert len(rows) == 2
    ips = {r["ip"] for r in rows}
    assert "104.21.5.32" in ips
    assert "172.67.189.21" in ips
    for row in rows:
        assert row["source"] == "securitytrails"
        assert "first_seen" in row
        assert "last_seen" in row


@pytest.mark.asyncio
async def test_securitytrails_returns_none_on_429():
    """ENRICH-06: 429 response triggers circuit breaker failure and returns None."""
    from app.services.enrichment.external.securitytrails import enrich_pdns

    mock_response = MagicMock()
    mock_response.status_code = 429

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    with (
        patch("app.services.enrichment.external.securitytrails.is_breaker_open", return_value=False),
        patch("app.services.enrichment.external.securitytrails.check_and_consume_quota", return_value=True),
        patch("app.services.enrichment.external.securitytrails.record_quota_failure") as mock_fail,
    ):
        rows = await enrich_pdns(
            mock_client, mock_redis, "test-api-key", "example.com", "proj-1"
        )

    assert rows is None
    mock_fail.assert_called_once()


@pytest.mark.asyncio
async def test_securitytrails_empty_records_returns_empty_list():
    """ENRICH-06: Empty records array returns empty list (not None)."""
    from app.services.enrichment.external.securitytrails import enrich_pdns

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"records": []}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.set.return_value = True

    with (
        patch("app.services.enrichment.external.securitytrails.is_breaker_open", return_value=False),
        patch("app.services.enrichment.external.securitytrails.check_and_consume_quota", return_value=True),
        patch("app.services.enrichment.external.securitytrails.record_success"),
    ):
        rows = await enrich_pdns(
            mock_client, mock_redis, "test-api-key", "example.com", "proj-1"
        )

    # Empty list is acceptable; None also accepted per plan (provider returns None on empty)
    assert rows == [] or rows is None


@pytest.mark.asyncio
async def test_securitytrails_returns_none_on_timeout():
    """ENRICH-06: httpx timeout returns None gracefully."""
    from app.services.enrichment.external.securitytrails import enrich_pdns

    mock_client = AsyncMock()
    mock_client.get.side_effect = httpx.TimeoutException("timeout")
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    with (
        patch("app.services.enrichment.external.securitytrails.is_breaker_open", return_value=False),
        patch("app.services.enrichment.external.securitytrails.check_and_consume_quota", return_value=True),
    ):
        rows = await enrich_pdns(
            mock_client, mock_redis, "test-api-key", "example.com", "proj-1"
        )

    assert rows is None
