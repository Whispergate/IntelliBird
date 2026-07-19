"""
DISINFO-01 - Social listening worker dispatches polls by platform and
             persists events via _persist_event_for_bindings.

Implemented in: backend/app/workers/social_worker.py
"""
import os
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

social_worker = pytest.importorskip(
    "app.workers.social_worker",
    reason="social_worker not yet implemented",
)


def test_poll_social_routes_by_platform():
    """poll_social_impl dispatches to the correct platform handler.

    Given a source with platform='mastodon', the mastodon handler is called
    and returns at least one mock post.  Verified by asserting that
    _persist_event_for_bindings is called at least once.
    """
    from unittest.mock import MagicMock, patch

    source_id = "00000000-0000-0000-0000-000000000001"

    fake_posts = [
        {"id": "m1", "content": "test post", "created_at": "2025-01-01T00:00:00Z"},
    ]

    with patch.object(social_worker, "_fetch_mastodon_posts", return_value=fake_posts):
        with patch.object(social_worker, "_persist_event_for_bindings", return_value=(1, 1)) as mock_persist:
            with patch.object(social_worker, "_open_session") as mock_session:
                mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
                mock_session.return_value.__exit__ = MagicMock(return_value=False)
                with patch.object(social_worker, "_fetch_source_row", return_value={
                    "id": source_id,
                    "url": "https://mastodon.social/@example",
                    "platform": "mastodon",
                    "credentials_enc": None,
                }):
                    social_worker.poll_social_impl(source_id)
                    assert mock_persist.call_count >= 1


def test_poll_social_persists_event():
    """poll_social_impl calls _persist_event_for_bindings once per post.

    Two posts in the feed → _persist_event_for_bindings called twice.
    """
    from unittest.mock import MagicMock, patch

    source_id = "00000000-0000-0000-0000-000000000002"

    fake_posts = [
        {"id": "p1", "content": "post one", "created_at": "2025-01-01T00:00:00Z"},
        {"id": "p2", "content": "post two", "created_at": "2025-01-01T01:00:00Z"},
    ]

    with patch.object(social_worker, "_fetch_mastodon_posts", return_value=fake_posts):
        with patch.object(social_worker, "_persist_event_for_bindings", return_value=(1, 1)) as mock_persist:
            with patch.object(social_worker, "_open_session") as mock_session:
                mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
                mock_session.return_value.__exit__ = MagicMock(return_value=False)
                with patch.object(social_worker, "_fetch_source_row", return_value={
                    "id": source_id,
                    "url": "https://mastodon.social/@example",
                    "platform": "mastodon",
                    "credentials_enc": None,
                }):
                    social_worker.poll_social_impl(source_id)
                    assert mock_persist.call_count == len(fake_posts)


def test_poll_social_handles_network_error():
    """poll_social_impl records 'network_error' health when HTTP fetch raises.

    When the platform fetch raises an exception (e.g. httpx.ConnectError),
    the worker calls update_source_health with status='network_error'.
    """
    from unittest.mock import MagicMock, patch
    import httpx

    source_id = "00000000-0000-0000-0000-000000000003"

    with patch.object(social_worker, "_fetch_mastodon_posts", side_effect=httpx.ConnectError("timeout")):
        with patch.object(social_worker, "update_source_health") as mock_health:
            with patch.object(social_worker, "_open_session") as mock_session:
                mock_session.return_value.__enter__ = MagicMock(return_value=MagicMock())
                mock_session.return_value.__exit__ = MagicMock(return_value=False)
                with patch.object(social_worker, "_fetch_source_row", return_value={
                    "id": source_id,
                    "url": "https://mastodon.social/@example",
                    "platform": "mastodon",
                    "credentials_enc": None,
                }):
                    social_worker.poll_social_impl(source_id)
                    mock_health.assert_called_once()
                    _, kwargs = mock_health.call_args
                    assert kwargs.get("status") == "network_error" or (
                        len(mock_health.call_args[0]) >= 3
                        and mock_health.call_args[0][2] == "network_error"
                    )
