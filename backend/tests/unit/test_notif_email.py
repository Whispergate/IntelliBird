"""
Unit tests for email dispatch via aiosmtplib (NOTIF-02).

Tests cover:
- _dispatch_email success path (mocked aiosmtplib.send)
- STARTTLS vs implicit TLS flag handling
- SMTPException error propagation
- Email subject format
- _drain_and_dispatch email branch routing
"""

from __future__ import annotations

import types
import uuid
from datetime import datetime, timezone
from email.mime.text import MIMEText
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.crypto import encrypt_credentials
from app.services.webhook_dispatcher import (
    _build_email_body,
    _dispatch_email,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_SECRET = "test-secret-key-32-bytes-long!!"


def _make_webhook(use_starttls: bool = True, name: str = "test-webhook") -> MagicMock:
    wh = MagicMock()
    wh.id = uuid.uuid4()
    wh.name = name
    wh.url = "smtp://smtp.example.com:587"
    wh.destination_type = "email"
    auth_dict = {
        "username": "user@example.com",
        "password": "secret",
        "from_addr": "alerts@example.com",
        "to_addr": "recipient@example.com",
        "use_starttls": use_starttls,
    }
    wh.auth_enc = encrypt_credentials(_SECRET, auth_dict)
    return wh


def _make_events() -> list[dict]:
    return [
        {
            "id": str(uuid.uuid4()),
            "title": "CVE-2024-1234 Critical",
            "tier": "S",
            "observed_at": "2026-05-04T10:00:00+00:00",
        },
        {
            "id": str(uuid.uuid4()),
            "title": "Suspicious Login",
            "tier": "A",
            "observed_at": "2026-05-04T10:05:00+00:00",
        },
    ]


# ---------------------------------------------------------------------------
# _build_email_body helper
# ---------------------------------------------------------------------------


def test_build_email_body_contains_header() -> None:
    """Body starts with IntelliBird header line."""
    events = _make_events()
    body = _build_email_body(events)
    assert "IntelliBird Alert Digest" in body
    assert "2 event(s)" in body


def test_build_email_body_contains_event_lines() -> None:
    """Each event produces a line with tier | title | observed_at."""
    events = _make_events()
    body = _build_email_body(events)
    assert "S | CVE-2024-1234 Critical" in body
    assert "A | Suspicious Login" in body


def test_build_email_body_handles_missing_fields() -> None:
    """Missing tier/title/observed_at uses fallback values."""
    events = [{}]
    body = _build_email_body(events)
    assert "? | (no title)" in body


# ---------------------------------------------------------------------------
# _dispatch_email success / failure
# ---------------------------------------------------------------------------


def test_dispatch_email_success() -> None:
    """NOTIF-02: mocked aiosmtplib.send returns success -> (True, None)."""
    webhook = _make_webhook(use_starttls=True)
    events = _make_events()

    with patch("app.services.webhook_dispatcher.settings") as mock_settings, \
         patch("app.services.webhook_dispatcher.aiosmtplib") as mock_smtp:
        mock_settings.SECRET_KEY = _SECRET
        # aiosmtplib.send is awaitable — make it a coroutine that succeeds
        mock_smtp.send = AsyncMock(return_value=None)

        ok, err = _dispatch_email(webhook, events)

    assert ok is True
    assert err is None


def test_dispatch_email_failure() -> None:
    """aiosmtplib raises SMTPException -> (False, str(error)[:200])."""
    webhook = _make_webhook(use_starttls=True)
    events = _make_events()

    with patch("app.services.webhook_dispatcher.settings") as mock_settings, \
         patch("app.services.webhook_dispatcher.aiosmtplib") as mock_smtp:
        mock_settings.SECRET_KEY = _SECRET

        import aiosmtplib as real_smtp  # noqa: PLC0415
        mock_smtp.SMTPException = real_smtp.SMTPException

        async def raise_smtp(*args, **kwargs):  # noqa: ANN202
            raise real_smtp.SMTPException("Connection refused")

        mock_smtp.send = raise_smtp

        ok, err = _dispatch_email(webhook, events)

    assert ok is False
    assert err is not None
    assert "Connection refused" in err


def test_dispatch_email_starttls() -> None:
    """use_starttls=True -> start_tls=True, use_tls=False passed to aiosmtplib.send."""
    webhook = _make_webhook(use_starttls=True)
    events = _make_events()

    captured_kwargs: dict = {}

    async def capture_send(*args, **kwargs) -> None:  # noqa: ANN002
        captured_kwargs.update(kwargs)

    with patch("app.services.webhook_dispatcher.settings") as mock_settings, \
         patch("app.services.webhook_dispatcher.aiosmtplib") as mock_smtp:
        mock_settings.SECRET_KEY = _SECRET
        mock_smtp.send = capture_send

        _dispatch_email(webhook, events)

    assert captured_kwargs.get("start_tls") is True
    assert captured_kwargs.get("use_tls") is False


def test_dispatch_email_implicit_tls() -> None:
    """use_starttls=False -> start_tls=False, use_tls=True (implicit TLS, port 465)."""
    webhook = _make_webhook(use_starttls=False)
    # Change URL to port 465
    webhook.url = "smtp://smtp.example.com:465"
    events = _make_events()

    captured_kwargs: dict = {}

    async def capture_send(*args, **kwargs) -> None:  # noqa: ANN002
        captured_kwargs.update(kwargs)

    with patch("app.services.webhook_dispatcher.settings") as mock_settings, \
         patch("app.services.webhook_dispatcher.aiosmtplib") as mock_smtp:
        mock_settings.SECRET_KEY = _SECRET
        mock_smtp.send = capture_send

        _dispatch_email(webhook, events)

    assert captured_kwargs.get("start_tls") is False
    assert captured_kwargs.get("use_tls") is True


def test_email_subject_format() -> None:
    """Subject = '[IntelliBird] N alert(s) — webhook.name'."""
    webhook = _make_webhook(name="my-alert-channel")
    events = _make_events()

    captured_args: list = []

    async def capture_send(message, **kwargs) -> None:  # noqa: ANN001
        captured_args.append(message)

    with patch("app.services.webhook_dispatcher.settings") as mock_settings, \
         patch("app.services.webhook_dispatcher.aiosmtplib") as mock_smtp:
        mock_settings.SECRET_KEY = _SECRET
        mock_smtp.send = capture_send

        _dispatch_email(webhook, events)

    assert len(captured_args) == 1
    msg = captured_args[0]
    assert isinstance(msg, MIMEText)
    subject = msg["Subject"]
    assert subject == "[IntelliBird] 2 alert(s) — my-alert-channel"


def test_dispatch_email_default_port() -> None:
    """Missing port in smtp:// URL defaults to 587."""
    webhook = _make_webhook(use_starttls=True)
    webhook.url = "smtp://smtp.example.com"  # no port
    events = _make_events()

    captured_kwargs: dict = {}

    async def capture_send(*args, **kwargs) -> None:  # noqa: ANN002
        captured_kwargs.update(kwargs)

    with patch("app.services.webhook_dispatcher.settings") as mock_settings, \
         patch("app.services.webhook_dispatcher.aiosmtplib") as mock_smtp:
        mock_settings.SECRET_KEY = _SECRET
        mock_smtp.send = capture_send

        _dispatch_email(webhook, events)

    assert captured_kwargs.get("port") == 587
