"""MON-04 monitoring admin API — plan 16-06.

Integration tests for the /api/admin/monitoring/sources REST endpoints:
list shape, per-source monitoring_config PATCH, and the Admin-only 403 gate
(Observer JWT must be rejected).

Mirrors the Phase 9 / Phase 13 admin test harness pattern (test_admin_users.py).
"""
from __future__ import annotations

import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

TEST_SIGNING_KEY = "j" * 64


# ---------------------------------------------------------------------------
# JWT mint helpers
# ---------------------------------------------------------------------------


def _mint_admin_token() -> str:
    from app.security.jwt import mint_access_token  # noqa: PLC0415

    token, _ = mint_access_token(
        str(uuid.uuid4()), "Admin", ["red", "blue"], 0, TEST_SIGNING_KEY
    )
    return token


def _mint_observer_token() -> str:
    from app.security.jwt import mint_access_token  # noqa: PLC0415

    token, _ = mint_access_token(
        str(uuid.uuid4()), "Viewer", ["blue"], 0, TEST_SIGNING_KEY
    )
    return token


def _patch_auth(monkeypatch) -> None:
    """Bypass DB token_version and Redis revocation checks."""
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
# App + client helpers
# ---------------------------------------------------------------------------


async def _client():
    from app.main import create_app  # noqa: PLC0415

    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


# ---------------------------------------------------------------------------
# test_admin_can_list_monitoring_sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_list_monitoring_sources(monkeypatch) -> None:
    """GET /api/admin/monitoring/sources returns 200 with source list for Admin JWT."""
    _patch_auth(monkeypatch)

    # Patch DB to return empty sources list — no live DB required
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = []

    from app.database import get_session  # noqa: PLC0415

    async def _mock_get_session():
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        yield mock_db

    from app.main import create_app  # noqa: PLC0415
    app = create_app()
    app.dependency_overrides[get_session] = _mock_get_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/admin/monitoring/sources",
                headers={"Authorization": f"Bearer {_mint_admin_token()}"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    assert isinstance(response.json(), list)


# ---------------------------------------------------------------------------
# test_non_admin_forbidden
# ---------------------------------------------------------------------------


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_non_admin_forbidden(monkeypatch) -> None:
    """GET /api/admin/monitoring/sources returns 403 for Observer JWT."""
    _patch_auth(monkeypatch)

    from app.main import create_app  # noqa: PLC0415
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/admin/monitoring/sources",
            headers={"Authorization": f"Bearer {_mint_observer_token()}"},
        )

    assert response.status_code == 403, f"Expected 403, got {response.status_code}"


# ---------------------------------------------------------------------------
# test_per_source_config_patch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_source_config_patch(monkeypatch) -> None:
    """PATCH /api/admin/monitoring/sources/{id} updates monitoring_config JSONB."""
    _patch_auth(monkeypatch)

    source_id = str(uuid.uuid4())

    call_count = {"n": 0}

    async def _mock_execute(stmt, params=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # SELECT to verify source exists
            mock_exists = MagicMock()
            mock_exists.fetchone.return_value = (source_id,)
            return mock_exists
        # UPDATE
        return MagicMock()

    from app.database import get_session  # noqa: PLC0415

    async def _mock_get_session():
        mock_db = AsyncMock()
        mock_db.execute = _mock_execute
        mock_db.commit = AsyncMock()
        yield mock_db

    from app.main import create_app  # noqa: PLC0415
    app = create_app()
    app.dependency_overrides[get_session] = _mock_get_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.patch(
                f"/api/admin/monitoring/sources/{source_id}",
                json={"last_event_sla_seconds": 3600},
                headers={"Authorization": f"Bearer {_mint_admin_token()}"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["last_event_sla_seconds"] == 3600
    assert data["last_changed_at"] is not None, "last_changed_at must be set on PATCH"
