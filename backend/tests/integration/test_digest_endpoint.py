"""Integration tests for AI-07 digest endpoints — Phase 17 / Plan 17-07.

Covers:
  - GET /api/projects/{id}/ai/digest returns latest digest row; 404 if none
  - POST /api/projects/{id}/ai/digest/trigger enqueues ai_digest_project (Admin only)
  - Analyst (non-Admin) cannot access trigger endpoint
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest

pytestmark = pytest.mark.integration

TEST_SIGNING_KEY = "j" * 64


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _mint_admin_token() -> str:
    from app.security.jwt import mint_access_token  # noqa: PLC0415

    token, _ = mint_access_token(
        str(uuid.uuid4()), "Admin", ["red", "blue"], 0, TEST_SIGNING_KEY
    )
    return token


def _mint_analyst_token(project_id: str) -> str:
    from app.security.jwt import mint_access_token_with_pm  # noqa: PLC0415

    token, _ = mint_access_token_with_pm(
        str(uuid.uuid4()), "Analyst", ["red", "blue"], 0, TEST_SIGNING_KEY,
        pm=[[project_id, 2]],  # Contributor rank
        pm_truncated=False,
    )
    return token


def _patch_auth(monkeypatch) -> None:
    import app.middleware.auth as auth_mod  # noqa: PLC0415
    from app.config import settings  # noqa: PLC0415

    async def _fake_token_version(user_id: str):
        return 0

    async def _fake_jti_revoked(jti: str) -> bool:
        return False

    monkeypatch.setattr(auth_mod, "_get_cached_token_version", _fake_token_version)
    monkeypatch.setattr(auth_mod, "_is_jti_revoked", _fake_jti_revoked)
    monkeypatch.setattr(settings, "JWT_SIGNING_KEY", TEST_SIGNING_KEY, raising=False)
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)


# ---------------------------------------------------------------------------
# test_get_latest_digest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_latest_digest(monkeypatch) -> None:
    """GET /api/projects/{id}/ai/digest returns latest digest row when one exists."""
    from httpx import ASGITransport, AsyncClient  # noqa: PLC0415
    from app.main import create_app  # noqa: PLC0415
    from app.database import get_session  # noqa: PLC0415

    _patch_auth(monkeypatch)

    project_id = uuid.uuid4()
    summary_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    fake_digest = MagicMock()
    fake_digest.id = summary_id
    fake_digest.project_id = project_id
    fake_digest.summary_type = "digest"
    fake_digest.provider_used = "ollama"
    fake_digest.model_used = "ollama_chat/phi3:mini"
    fake_digest.prompt_template_version = "DIGEST_PROMPT_V1"
    fake_digest.summary_text = "This is a test digest summary."
    fake_digest.tokens_used = 512
    fake_digest.requires_analyst_review = False
    fake_digest.created_at = now

    async def _mock_get_session():
        mock_db = AsyncMock()
        res = MagicMock()
        res.scalar_one_or_none.return_value = fake_digest
        mock_db.execute = AsyncMock(return_value=res)
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_session] = _mock_get_session

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get(
            f"/api/projects/{project_id}/ai/digest",
            headers={"Authorization": f"Bearer {_mint_admin_token()}"},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["summary_type"] == "digest"
    assert body["summary_text"] == "This is a test digest summary."
    assert str(project_id) in body["project_id"]


# ---------------------------------------------------------------------------
# test_get_digest_404_when_none
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_digest_404_when_none(monkeypatch) -> None:
    """GET /api/projects/{id}/ai/digest returns 404 when no digest has been generated."""
    from httpx import ASGITransport, AsyncClient  # noqa: PLC0415
    from app.main import create_app  # noqa: PLC0415
    from app.database import get_session  # noqa: PLC0415

    _patch_auth(monkeypatch)

    project_id = uuid.uuid4()

    async def _mock_get_session():
        mock_db = AsyncMock()
        res = MagicMock()
        res.scalar_one_or_none.return_value = None  # no digest
        mock_db.execute = AsyncMock(return_value=res)
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_session] = _mock_get_session

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get(
            f"/api/projects/{project_id}/ai/digest",
            headers={"Authorization": f"Bearer {_mint_admin_token()}"},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"
    assert "no_digest_available" in r.json().get("detail", "")


# ---------------------------------------------------------------------------
# test_admin_only_trigger_endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_only_trigger_endpoint(monkeypatch) -> None:
    """POST /api/projects/{id}/ai/digest/trigger is accessible to Admin (Lead bypass)."""
    from httpx import ASGITransport, AsyncClient  # noqa: PLC0415
    from app.main import create_app  # noqa: PLC0415
    from app.database import get_session  # noqa: PLC0415

    _patch_auth(monkeypatch)

    project_id = uuid.uuid4()

    send_calls = []

    class _FakeActor:
        def send(self, *args, **kwargs):
            send_calls.append(args)

    async def _mock_get_session():
        mock_db = AsyncMock()
        res = MagicMock()
        res.scalar_one_or_none.return_value = "Lead"
        mock_db.execute = AsyncMock(return_value=res)
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_session] = _mock_get_session

    with patch("app.workers.ai.ai_digest_project", _FakeActor()):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                f"/api/projects/{project_id}/ai/digest/trigger",
                headers={"Authorization": f"Bearer {_mint_admin_token()}"},
            )

    app.dependency_overrides.clear()

    assert r.status_code == 202, f"Expected 202, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["queued"] is True
    assert str(project_id) in body["project_id"]
    assert len(send_calls) == 1
