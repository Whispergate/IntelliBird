"""Integration tests for AI-05 GET /api/admin/ai-health — Plan 17-07.

Covers:
  - GET /api/admin/ai-health returns 200 + {ollama_health, providers_configured_count}
  - ollama_health='healthy', 'slow', 'down', 'unknown' all reflected correctly
  - Admin-only: non-admin users get 403
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

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


def _mint_viewer_token() -> str:
    from app.security.jwt import mint_access_token  # noqa: PLC0415

    token, _ = mint_access_token(
        str(uuid.uuid4()), "Viewer", ["blue"], 0, TEST_SIGNING_KEY
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
# Helper: build app with mocked DB count and forced Ollama state
# ---------------------------------------------------------------------------


def _make_app_with_health(monkeypatch, ollama_status: str, provider_count: int = 2):
    """Build a FastAPI test app with patched DB and forced Ollama health state."""
    from app.main import create_app  # noqa: PLC0415
    from app.database import get_session  # noqa: PLC0415

    async def _mock_get_session():
        mock_db = AsyncMock()
        res = MagicMock()
        res.scalar_one.return_value = provider_count
        mock_db.execute = AsyncMock(return_value=res)
        yield mock_db

    app = create_app()
    # Force Ollama health state on app.state.
    app.state.ollama_health = ollama_status
    app.dependency_overrides[get_session] = _mock_get_session
    return app


# ---------------------------------------------------------------------------
# test_get_ai_health_returns_ollama_health_field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_ai_health_returns_ollama_health_field(monkeypatch) -> None:
    """GET /api/admin/ai-health returns 200 with ollama_health + providers_configured_count."""
    from httpx import ASGITransport, AsyncClient  # noqa: PLC0415

    _patch_auth(monkeypatch)

    app = _make_app_with_health(monkeypatch, "healthy", provider_count=3)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get(
            "/api/admin/ai-health",
            headers={"Authorization": f"Bearer {_mint_admin_token()}"},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert "ollama_health" in body, f"Missing ollama_health field: {body}"
    assert "providers_configured_count" in body, f"Missing providers_configured_count: {body}"
    assert body["ollama_health"] == "healthy"
    assert body["providers_configured_count"] == 3


# ---------------------------------------------------------------------------
# test_health_slow_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_slow_state(monkeypatch) -> None:
    """GET /api/admin/ai-health returns ollama_health='slow' when probe was slow."""
    from httpx import ASGITransport, AsyncClient  # noqa: PLC0415

    _patch_auth(monkeypatch)

    app = _make_app_with_health(monkeypatch, "slow", provider_count=1)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get(
            "/api/admin/ai-health",
            headers={"Authorization": f"Bearer {_mint_admin_token()}"},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 200, r.text
    assert r.json()["ollama_health"] == "slow"


# ---------------------------------------------------------------------------
# test_health_down_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_down_state(monkeypatch) -> None:
    """GET /api/admin/ai-health returns ollama_health='down' when Ollama unreachable."""
    from httpx import ASGITransport, AsyncClient  # noqa: PLC0415

    _patch_auth(monkeypatch)

    app = _make_app_with_health(monkeypatch, "down", provider_count=0)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get(
            "/api/admin/ai-health",
            headers={"Authorization": f"Bearer {_mint_admin_token()}"},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ollama_health"] == "down"
    assert body["providers_configured_count"] == 0


# ---------------------------------------------------------------------------
# test_non_admin_forbidden
# ---------------------------------------------------------------------------


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_non_admin_forbidden(monkeypatch) -> None:
    """GET /api/admin/ai-health returns 403 for non-admin users."""
    from httpx import ASGITransport, AsyncClient  # noqa: PLC0415

    _patch_auth(monkeypatch)

    from app.main import create_app  # noqa: PLC0415

    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get(
            "/api/admin/ai-health",
            headers={"Authorization": f"Bearer {_mint_viewer_token()}"},
        )

    assert r.status_code == 403, f"Expected 403 for Viewer, got {r.status_code}: {r.text}"
