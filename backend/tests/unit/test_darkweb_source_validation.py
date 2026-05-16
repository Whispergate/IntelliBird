"""Unit tests for dark-web source OPSEC gate and input validation — Phase 24 / DARK-07."""
import os

import pytest

# Minimal env to satisfy Settings validation at import time.
os.environ.setdefault("SECRET_KEY", "a" * 32)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
os.environ.setdefault("JWT_SIGNING_KEY", "b" * 32)

from fastapi import HTTPException  # noqa: E402

from app.routers.admin.sources import _validate_dark_web_source  # noqa: E402


def test_opsec_gate_rejects_tor_html_without_authorisation():
    """POST /api/admin/sources with feed_type='tor_html' and opsec_authorised=False → HTTP 422"""
    with pytest.raises(HTTPException) as exc_info:
        _validate_dark_web_source("tor_html", "http://some.onion/", False, 3600)
    assert exc_info.value.status_code == 422
    assert "opsec_authorised" in exc_info.value.detail


def test_opsec_gate_rejects_paste_without_authorisation():
    """POST /api/admin/sources with feed_type='paste' and opsec_authorised=False → HTTP 422"""
    with pytest.raises(HTTPException) as exc_info:
        _validate_dark_web_source("paste", "https://paste.ee/", False, 3600)
    assert exc_info.value.status_code == 422
    assert "opsec_authorised" in exc_info.value.detail


def test_opsec_gate_rejects_telegram_without_authorisation():
    """POST /api/admin/sources with feed_type='telegram' and opsec_authorised=False → HTTP 422"""
    with pytest.raises(HTTPException) as exc_info:
        _validate_dark_web_source("telegram", "@channelusername", False, 3600)
    assert exc_info.value.status_code == 422
    assert "opsec_authorised" in exc_info.value.detail


def test_opsec_gate_allows_dark_web_with_authorisation():
    """POST with feed_type='tor_html' and opsec_authorised=True → no exception raised"""
    # Should not raise — returns None
    result = _validate_dark_web_source("tor_html", "http://some.onion/", True, 3600)
    assert result is None


def test_opsec_gate_does_not_block_rss_or_taxii():
    """feed_type='rss' with opsec_authorised=False → gate does not apply"""
    # rss is a clearnet type — no OPSEC gate
    result = _validate_dark_web_source("rss", "https://example.com/feed.rss", False, 60)
    assert result is None

    # taxii is also clearnet — no OPSEC gate
    result = _validate_dark_web_source("taxii", "https://taxii.example.com/", False, 60)
    assert result is None


def test_telegram_rejects_joinchat_private_invite():
    """url containing '/joinchat/' → HTTP 422 Telegram private invite not allowed"""
    with pytest.raises(HTTPException) as exc_info:
        _validate_dark_web_source(
            "telegram", "https://t.me/joinchat/AAAAABcdEFGH", True, 3600
        )
    assert exc_info.value.status_code == 422
    assert "joinchat" in exc_info.value.detail


def test_telegram_rejects_plus_prefixed_invite():
    """url t.me/+PrivateToken → HTTP 422"""
    with pytest.raises(HTTPException) as exc_info:
        _validate_dark_web_source(
            "telegram", "https://t.me/+PrivateInviteToken", True, 3600
        )
    assert exc_info.value.status_code == 422
    assert "+" in exc_info.value.detail or "invite" in exc_info.value.detail.lower()


def test_paste_enforces_minimum_300s_poll_interval():
    """paste source with poll_interval_sec=60 → HTTP 422 minimum 300s required"""
    with pytest.raises(HTTPException) as exc_info:
        _validate_dark_web_source("paste", "https://paste.ee/", True, 60)
    assert exc_info.value.status_code == 422
    assert "300" in exc_info.value.detail


def test_paste_allows_300s_poll_interval():
    """paste source with poll_interval_sec=300 → no exception raised"""
    result = _validate_dark_web_source("paste", "https://paste.ee/", True, 300)
    assert result is None
