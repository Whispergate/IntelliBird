"""
Tests for dispatcher routing, GenieKey headers, and PD routing_key body injection (NOTIF-05).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.crypto import encrypt_credentials
from app.services.webhook_dispatcher import _build_auth_headers, _drain_and_dispatch


# ---------------------------------------------------------------------------
# Auth header construction
# ---------------------------------------------------------------------------

_SECRET = "test-secret-key-32-bytes-long!!"


def _enc(creds: dict) -> str:
    return encrypt_credentials(_SECRET, creds)


def test_build_auth_headers_geniekey() -> None:
    """NOTIF-05: {'type':'geniekey','api_key':'x'} → {'Authorization':'GenieKey x'}."""
    auth_enc = _enc({"type": "geniekey", "api_key": "test_api_key"})
    with patch("app.services.webhook_dispatcher.settings") as mock_settings:
        mock_settings.SECRET_KEY = _SECRET
        result = _build_auth_headers(auth_enc)
    assert result == {"Authorization": "GenieKey test_api_key"}


def test_build_auth_headers_bearer_unchanged() -> None:
    """Existing Bearer branch still produces Authorization: Bearer <token>."""
    auth_enc = _enc({"type": "bearer", "token": "my_bearer_token"})
    with patch("app.services.webhook_dispatcher.settings") as mock_settings:
        mock_settings.SECRET_KEY = _SECRET
        result = _build_auth_headers(auth_enc)
    assert result == {"Authorization": "Bearer my_bearer_token"}


# ---------------------------------------------------------------------------
# Dispatcher routing (stubs for later plans)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="stub — implementation pending in plan 30-04/30-05")
def test_drain_dispatch_email_branch() -> None:
    """destination_type='email' calls _dispatch_email, NOT _post_with_retry."""
    pytest.skip("stub")


# ---------------------------------------------------------------------------
# PagerDuty auto-resolve (stub for later plans)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="stub — implementation pending in plan 30-04/30-05")
def test_pd_auto_resolve() -> None:
    """Archiver hook fires HTTP POST with event_action='resolve' on archived events."""
    pytest.skip("stub")
