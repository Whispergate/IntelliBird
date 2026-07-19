"""Unit tests for WHOIS service - ENRICH-07.

Tests 7-day refetch suppression logic. Uses a real in-memory SQLite session
where possible, or mocks the SQL execution to simulate cache state.

NOTE: asyncwhois is patched - no real DNS/WHOIS calls in unit tests.
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta


@pytest.mark.asyncio
async def test_whois_cache_hit_within_7_days():
    """ENRICH-07: whois_cache row fetched within 7 days is returned without a new API call.

    We mock the SQLAlchemy session's execute() to simulate a fresh row (3 days old)
    in whois_cache. The TTL gate should find it and return immediately - asyncwhois
    must NOT be called.
    """
    from app.services.whois import fetch_and_cache_whois

    domain = "fresh-whois-test.example.com"
    now = datetime.now(timezone.utc)

    # Simulate the TTL-gate SELECT returning a row (fresh, within 7 days)
    fresh_row = {
        "id": 1,
        "domain": domain,
        "registrar": "Test Registrar",
        "registrant_email": "admin@fresh-whois-test.example.com",
        "registration_date": None,
        "expiry_date": None,
        "nameservers": [],
        "fetched_at": now - timedelta(days=3),
        "raw_json": {},
    }

    mock_session = AsyncMock()

    # First execute call: TTL gate SELECT - returns the fresh row
    ttl_result = MagicMock()
    ttl_result.mappings.return_value.first.return_value = fresh_row

    # Second execute call: full SELECT * - returns same row
    full_result = MagicMock()
    full_result.mappings.return_value.first.return_value = fresh_row

    mock_session.execute.side_effect = [ttl_result, full_result]

    mock_redis = AsyncMock()

    with patch("app.services.whois.asyncwhois.aio_whois") as mock_aio:
        mock_aio.return_value = ("", {})  # should NOT be called
        result = await fetch_and_cache_whois(mock_session, mock_redis, domain)

    # asyncwhois must not have been called - cache hit suppresses it
    mock_aio.assert_not_called()
    assert result is not None


@pytest.mark.asyncio
async def test_whois_stale_row_triggers_refetch():
    """ENRICH-07: whois_cache row older than 7 days triggers a new API call.

    We mock the SQLAlchemy session's execute() to simulate a stale row (8 days old).
    The TTL gate returns None (no fresh row). asyncwhois should be called once.
    """
    from app.services.whois import fetch_and_cache_whois

    domain = "stale-whois-test.example.com"
    now = datetime.now(timezone.utc)

    # Simulate the TTL gate returning None (stale row - outside 7-day window)
    ttl_result = MagicMock()
    ttl_result.mappings.return_value.first.return_value = None  # cache miss

    # After upsert, return the newly updated row
    fresh_row = {
        "id": 1,
        "domain": domain,
        "registrar": "New Registrar",
        "registrant_email": "admin@stale-whois-test.example.com",
        "registration_date": None,
        "expiry_date": None,
        "nameservers": ["ns1.test.example.com"],
        "fetched_at": now,
        "raw_json": {"registrar": "New Registrar"},
    }
    post_upsert_result = MagicMock()
    post_upsert_result.mappings.return_value.first.return_value = fresh_row

    mock_session = AsyncMock()
    # First: TTL gate returns None; subsequent calls return fresh row
    mock_session.execute.side_effect = [ttl_result, MagicMock(), post_upsert_result]
    mock_session.commit = AsyncMock()

    mock_redis = AsyncMock()
    mock_redis.set.return_value = True    # lock acquired
    mock_redis.get.return_value = None
    mock_redis.delete.return_value = True

    fresh_parsed = {
        "registrar": "New Registrar",
        "registrant_email": "admin@stale-whois-test.example.com",
        "created": datetime(2020, 1, 1, tzinfo=timezone.utc),
        "expires": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "name_servers": ["ns1.test.example.com"],
        "emails": ["admin@stale-whois-test.example.com"],
    }

    with patch("app.services.whois.asyncwhois.aio_whois", new_callable=AsyncMock) as mock_aio:
        mock_aio.return_value = ("raw whois string", fresh_parsed)
        result = await fetch_and_cache_whois(mock_session, mock_redis, domain)

    mock_aio.assert_called_once_with(domain, ignore_returned_errors=True)
    # Result should have new registrar data
    assert result is not None
