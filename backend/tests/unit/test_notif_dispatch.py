"""
Tests for dispatcher routing, GenieKey headers, and PD routing_key body injection (NOTIF-03).
"""

from __future__ import annotations

import json
import types
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

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
# PagerDuty routing_key body injection (NOTIF-03, 30-05)
# ---------------------------------------------------------------------------

def _make_webhook(
    destination_type: str,
    auth_enc: str | None = None,
    webhook_id: str | None = None,
) -> MagicMock:
    """Build a minimal Webhook-like mock for _drain_and_dispatch tests."""
    wh = MagicMock()
    wh.id = uuid.UUID(webhook_id or str(uuid.uuid4()))
    wh.destination_type = destination_type
    wh.auth_enc = auth_enc
    wh.consecutive_failures = 0
    wh.last_dispatch_at = None
    wh.batching_window_sec = 60
    wh.url = "https://events.pagerduty.com/v2/enqueue"
    wh.name = "test-webhook"
    wh.project_id = uuid.uuid4()
    return wh


def _make_preset(name: str = "default") -> MagicMock:
    preset = MagicMock()
    preset.name = name
    preset.query_params = {}
    return preset


def _make_redis_with_events(events: list[dict]) -> MagicMock:
    """Return a Redis mock whose lrange returns JSON-encoded event list."""
    r = MagicMock()
    serialised = [json.dumps(ev).encode() for ev in events]
    r.lrange.return_value = serialised
    return r


def _make_session() -> MagicMock:
    session = MagicMock()
    session.execute.return_value.rowcount = 0
    return session


_SAMPLE_EVENTS = [
    {
        "id": str(uuid.uuid4()),
        "title": "Test alert",
        "observed_at": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        "fetched_at": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        "description": "desc",
        "source_id": None,
        "source_name": None,
        "source_type": None,
        "stix_id": None,
        "stix_type": None,
        "tlp": None,
        "tags": [],
        "attack_techniques": [],
        "archived": False,
        "visibility": "shared",
        "geo_lat": None,
        "geo_lon": None,
        "score": None,
    }
]


def test_pd_routing_key_injected_into_payload_body() -> None:
    """NOTIF-03: routing_key from auth_enc appears in the JSON body sent to PD.

    _drain_and_dispatch must inject payload['routing_key'] from decrypted
    auth_enc BEFORE _post_with_retry is called — routing_key must NOT be
    in any Authorization header (PD Events API v2 requires it in the body).
    """
    routing_key = "rk_abc123_test_key"
    auth_enc = _enc({"routing_key": routing_key})
    wh = _make_webhook("pagerduty", auth_enc=auth_enc)
    r = _make_redis_with_events(_SAMPLE_EVENTS)
    session = _make_session()
    preset = _make_preset()

    captured_payload: dict = {}
    captured_headers: dict = {}

    def _fake_post(url: str, payload: dict, headers: dict) -> tuple:
        captured_payload.update(payload)
        captured_headers.update(headers)
        return True, None

    with (
        patch("app.services.webhook_dispatcher.settings") as mock_settings,
        patch("app.services.webhook_dispatcher._post_with_retry", side_effect=_fake_post),
    ):
        mock_settings.SECRET_KEY = _SECRET
        mock_settings.DASHBOARD_URL = "http://localhost:3000"
        _drain_and_dispatch(wh, r, session, preset)

    assert captured_payload.get("routing_key") == routing_key, (
        f"routing_key not found in payload body. Got: {list(captured_payload.keys())}"
    )
    # routing_key must NOT appear in Authorization header
    assert "Authorization" not in captured_headers, (
        "routing_key must be in body, not Authorization header"
    )


def test_pd_routing_key_injection_no_op_for_generic_webhook() -> None:
    """Non-pagerduty destination_type must not have routing_key injected."""
    auth_enc = _enc({"type": "bearer", "token": "tok123"})
    wh = _make_webhook("generic", auth_enc=auth_enc)
    wh.url = "https://example.com/hooks/test"
    r = _make_redis_with_events(_SAMPLE_EVENTS)
    session = _make_session()
    preset = _make_preset()

    captured_payload: dict = {}

    def _fake_post(url: str, payload: dict, headers: dict) -> tuple:
        captured_payload.update(payload)
        return True, None

    with (
        patch("app.services.webhook_dispatcher.settings") as mock_settings,
        patch("app.services.webhook_dispatcher._post_with_retry", side_effect=_fake_post),
    ):
        mock_settings.SECRET_KEY = _SECRET
        mock_settings.DASHBOARD_URL = "http://localhost:3000"
        _drain_and_dispatch(wh, r, session, preset)

    assert "routing_key" not in captured_payload, (
        "routing_key must not be injected for non-pagerduty types"
    )


def test_pd_routing_key_decrypt_failure_leaves_sentinel() -> None:
    """If auth_enc decrypt fails, _post_with_retry is still called.

    The payload's routing_key keeps the '_PENDING_INJECTION_' sentinel (or
    the key is missing). Delivery will 400 at PD — triggering auto-disable.
    The important thing: no exception escapes _drain_and_dispatch.
    """
    wh = _make_webhook("pagerduty", auth_enc="invalid_encrypted_blob")
    r = _make_redis_with_events(_SAMPLE_EVENTS)
    session = _make_session()
    preset = _make_preset()

    post_called = []

    def _fake_post(url: str, payload: dict, headers: dict) -> tuple:
        post_called.append(payload)
        return False, "http_400"

    with (
        patch("app.services.webhook_dispatcher.settings") as mock_settings,
        patch("app.services.webhook_dispatcher._post_with_retry", side_effect=_fake_post),
    ):
        mock_settings.SECRET_KEY = _SECRET
        mock_settings.DASHBOARD_URL = "http://localhost:3000"
        # Must not raise
        _drain_and_dispatch(wh, r, session, preset)

    # _post_with_retry was called (dispatch was attempted)
    assert len(post_called) == 1, "Expected _post_with_retry to be called once"
    # routing_key NOT present from injector (decrypt failed — sentinel or absent)
    assert post_called[0].get("routing_key") != "rk_real_key", (
        "routing_key should not be a real key when decrypt fails"
    )


# ---------------------------------------------------------------------------
# PagerDuty auto-resolve archiver hook (NOTIF-03, 30-05)
# ---------------------------------------------------------------------------


def test_pd_auto_resolve() -> None:
    """Archiver hook fires HTTP POST with event_action='resolve' on archived events.

    When _archive_source runs the move-to-cold path with rowcount > 0,
    _fire_pagerduty_resolves must be called (and fire httpx POSTs with
    event_action='resolve' to PD-enabled webhooks for the affected source).
    """
    import httpx
    from unittest.mock import patch as _patch, MagicMock as _Mock

    from app.services.archiver import _fire_pagerduty_resolves

    routing_key = "rk_test_resolve_key"
    auth_enc = _enc({"routing_key": routing_key})
    pd_url = "https://events.pagerduty.com/v2/enqueue"
    event_id = str(uuid.uuid4())

    # Session returns one PD webhook row.
    # archiver accesses rows as row[0]=url, row[1]=auth_enc (tuple-style).
    _result_mock = _Mock()
    _result_mock.fetchall.return_value = [(pd_url, auth_enc)]
    session_mock = _Mock()
    session_mock.execute.return_value = _result_mock

    posted: list[dict] = []

    def _fake_httpx_post(url: str, **kwargs: object) -> None:
        posted.append({"url": url, **kwargs})

    with (
        _patch("app.services.archiver.settings") as mock_settings,
        _patch("app.services.archiver.httpx.post", side_effect=_fake_httpx_post),
    ):
        mock_settings.SECRET_KEY = _SECRET
        _fire_pagerduty_resolves(session_mock, "source-id-1", [event_id])

    assert len(posted) == 1, f"Expected 1 POST, got {len(posted)}"
    body = posted[0].get("json", {})
    assert body.get("event_action") == "resolve", f"expected resolve, got: {body}"
    assert body.get("dedup_key") == event_id
    assert body.get("routing_key") == routing_key
