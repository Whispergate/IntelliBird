"""MON-05 maintenance window CRUD — plan 16-06.

Integration tests for the maintenance window REST endpoints:
Admin-only POST/GET/DELETE CRUD, the is_maintenance_active() service helper,
and the 403 gate for non-admin callers.

Mirrors the Phase 9 / Phase 13 admin test harness (test_admin_users.py).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.services.maintenance import is_maintenance_active  # noqa: E402

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
# test_is_maintenance_active_helper (unit test — no DB required)
# ---------------------------------------------------------------------------


def test_is_maintenance_active_helper() -> None:
    """is_maintenance_active() returns correct True/False for 4 cases."""
    # Case 1: No rows → returns False
    session_empty = MagicMock()
    session_empty.execute.return_value.fetchone.return_value = None
    assert is_maintenance_active(session_empty) is False

    # Case 2: Active window → returns True
    session_active = MagicMock()
    session_active.execute.return_value.fetchone.return_value = (1,)
    assert is_maintenance_active(session_active) is True

    # Case 3: Past window → query returns None
    session_past = MagicMock()
    session_past.execute.return_value.fetchone.return_value = None
    assert is_maintenance_active(session_past) is False

    # Case 4: Future window → query returns None
    session_future = MagicMock()
    session_future.execute.return_value.fetchone.return_value = None
    assert is_maintenance_active(session_future) is False


# ---------------------------------------------------------------------------
# test_admin_creates_window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_creates_window(monkeypatch) -> None:
    """POST /api/admin/maintenance-window returns 201 for Admin JWT."""
    _patch_auth(monkeypatch)

    now = datetime.now(timezone.utc)

    from app.database import get_session  # noqa: PLC0415

    async def _mock_get_session():
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        mock_db.commit = AsyncMock()
        yield mock_db

    from app.main import create_app  # noqa: PLC0415
    app = create_app()
    app.dependency_overrides[get_session] = _mock_get_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/admin/maintenance-window",
                json={
                    "start_at": now.isoformat(),
                    "end_at": (now + timedelta(hours=2)).isoformat(),
                    "reason": "Planned stack restart",
                },
                headers={"Authorization": f"Bearer {_mint_admin_token()}"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
    data = response.json()
    assert "id" in data


# ---------------------------------------------------------------------------
# test_admin_creates_window_invalid_end_at
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_creates_window_invalid_end_at(monkeypatch) -> None:
    """POST returns 422 when end_at <= start_at."""
    _patch_auth(monkeypatch)

    now = datetime.now(timezone.utc)

    from app.main import create_app  # noqa: PLC0415
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/admin/maintenance-window",
            json={
                "start_at": now.isoformat(),
                "end_at": now.isoformat(),  # equal — not valid
            },
            headers={"Authorization": f"Bearer {_mint_admin_token()}"},
        )

    assert response.status_code == 422, f"Expected 422, got {response.status_code}"


# ---------------------------------------------------------------------------
# test_admin_lists_windows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_lists_windows(monkeypatch) -> None:
    """GET /api/admin/maintenance-window returns list of windows."""
    _patch_auth(monkeypatch)

    now = datetime.now(timezone.utc)
    window_id = str(uuid.uuid4())

    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, key: {
        "id": window_id,
        "start_at": now,
        "end_at": now + timedelta(hours=2),
        "reason": "Test maintenance",
        "created_by_user_id": None,
        "created_at": now,
    }[key]

    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = [mock_row]

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
                "/api/admin/maintenance-window",
                headers={"Authorization": f"Bearer {_mint_admin_token()}"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["id"] == window_id


# ---------------------------------------------------------------------------
# test_admin_deletes_window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_deletes_window(monkeypatch) -> None:
    """DELETE /api/admin/maintenance-window/{id} → 204 No Content."""
    _patch_auth(monkeypatch)

    window_id = str(uuid.uuid4())

    mock_result = MagicMock()
    mock_result.fetchone.return_value = (window_id,)

    from app.database import get_session  # noqa: PLC0415

    async def _mock_get_session():
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        yield mock_db

    from app.main import create_app  # noqa: PLC0415
    app = create_app()
    app.dependency_overrides[get_session] = _mock_get_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.delete(
                f"/api/admin/maintenance-window/{window_id}",
                headers={"Authorization": f"Bearer {_mint_admin_token()}"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204, f"Expected 204, got {response.status_code}"


# ---------------------------------------------------------------------------
# test_non_admin_forbidden
# ---------------------------------------------------------------------------


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_non_admin_forbidden(monkeypatch) -> None:
    """POST /api/admin/maintenance-window returns 403 for Observer JWT."""
    _patch_auth(monkeypatch)

    now = datetime.now(timezone.utc)

    from app.main import create_app  # noqa: PLC0415
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/admin/maintenance-window",
            json={
                "start_at": now.isoformat(),
                "end_at": (now + timedelta(hours=1)).isoformat(),
            },
            headers={"Authorization": f"Bearer {_mint_observer_token()}"},
        )

    assert response.status_code == 403, f"Expected 403, got {response.status_code}"


# ---------------------------------------------------------------------------
# test_active_window_404_when_none
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_window_404_when_none(monkeypatch) -> None:
    """GET /api/admin/maintenance-window/active returns 404 when no active window."""
    _patch_auth(monkeypatch)

    mock_result = MagicMock()
    mock_result.mappings.return_value.fetchone.return_value = None

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
                "/api/admin/maintenance-window/active",
                headers={"Authorization": f"Bearer {_mint_admin_token()}"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
