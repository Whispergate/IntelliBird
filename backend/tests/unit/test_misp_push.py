"""
MISP-03 — Validated AI suggestions pushed to MISP as proposals via Dramatiq actor
          misp_push_suggestion. Only fires on 'confirmed' status + opt-in push_types.

Implemented in: backend/app/workers/misp_push.py
"""
import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)


@pytest.mark.xfail(reason="misp_push actor not yet implemented", strict=False)
def test_only_confirmed_triggers_push():
    """_maybe_push_to_misp only enqueues misp_push_suggestion on status='confirmed'."""
    from app.workers.misp_push import _should_push
    assert _should_push(status="confirmed", suggestion_type="cve", push_types=["cve"]) is True
    assert _should_push(status="pending", suggestion_type="cve", push_types=["cve"]) is False
    assert _should_push(status="discarded", suggestion_type="cve", push_types=["cve"]) is False


@pytest.mark.xfail(reason="misp_push actor not yet implemented", strict=False)
def test_push_respects_opt_in_types():
    """_should_push returns False when suggestion_type not in push_types."""
    from app.workers.misp_push import _should_push
    assert _should_push(status="confirmed", suggestion_type="actor", push_types=["cve"]) is False
    assert _should_push(status="confirmed", suggestion_type="cve", push_types=[]) is False


@pytest.mark.xfail(reason="misp_push actor not yet implemented", strict=False)
def test_push_actor_is_dramatiq_actor():
    """misp_push_suggestion is a Dramatiq actor on the 'ingest' queue."""
    import dramatiq
    from app.workers.misp_push import misp_push_suggestion
    assert isinstance(misp_push_suggestion, dramatiq.Actor)
    assert misp_push_suggestion.queue_name == "ingest"
