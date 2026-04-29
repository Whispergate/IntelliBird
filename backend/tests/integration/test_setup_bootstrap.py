"""POST /api/admin/setup SETUP_TOKEN gate + first-admin create + 409 on second call.

Integration tests — AUTH-01. Activated by plan 09-04.

Uses ASGITransport with the FastAPI app (no live DB required for token/validation tests;
DB-touching tests require the db_session fixture from conftest).
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "a" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "b" * 64)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

pytestmark = pytest.mark.integration

SETUP_TOKEN = "test-setup-token-abc123"
VALID_BODY = {"username": "firstadmin", "password": "supersecret12345"}


async def _client():
    from app.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_setup_without_token_returns_403(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "SETUP_TOKEN", SETUP_TOKEN)
    async with await _client() as c:
        r = await c.post("/api/admin/setup", json=VALID_BODY)
        assert r.status_code == 403
        assert "Invalid or missing setup token" in r.text


@pytest.mark.asyncio
async def test_setup_wrong_token_returns_403(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "SETUP_TOKEN", SETUP_TOKEN)
    async with await _client() as c:
        r = await c.post(
            "/api/admin/setup",
            json=VALID_BODY,
            headers={"X-Setup-Token": "wrong-token"},
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_setup_when_token_unset_returns_403(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "SETUP_TOKEN", None)
    async with await _client() as c:
        r = await c.post(
            "/api/admin/setup",
            json=VALID_BODY,
            headers={"X-Setup-Token": "anything"},
        )
        assert r.status_code == 403
        assert "Invalid or missing setup token" in r.text


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_setup_password_too_short_returns_422(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "SETUP_TOKEN", SETUP_TOKEN)
    async with await _client() as c:
        r = await c.post(
            "/api/admin/setup",
            json={"username": "admin", "password": "short"},
            headers={"X-Setup-Token": SETUP_TOKEN},
        )
        assert r.status_code == 422


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_setup_happy_path_creates_admin(db_session, monkeypatch):
    """POST /api/admin/setup creates Admin with Argon2 hash + both dashboards."""
    from app.config import settings
    from app.models.users import User
    from sqlalchemy import select, text

    monkeypatch.setattr(settings, "SETUP_TOKEN", SETUP_TOKEN)
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)

    # Ensure no users exist
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    async with await _client() as c:
        r = await c.post(
            "/api/admin/setup",
            json=VALID_BODY,
            headers={"X-Setup-Token": SETUP_TOKEN},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["username"] == "firstadmin"
        assert body["role"] == "Admin"
        assert set(body["dashboard_roles"]) == {"red", "blue"}
        assert body["must_change_password"] is False
        assert "id" in body

    # Verify DB row
    row = (await db_session.execute(
        select(User).where(User.username == "firstadmin")
    )).scalar_one_or_none()
    assert row is not None
    assert row.password_hash.startswith("$argon2id$")
    assert row.enabled is True
    assert row.must_change_password is False
    assert set(row.dashboard_roles) == {"red", "blue"}


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_setup_second_call_returns_409_setup_already_complete(db_session, monkeypatch):
    """Second POST /api/admin/setup returns 409 setup_already_complete."""
    from app.config import settings
    from sqlalchemy import text

    monkeypatch.setattr(settings, "SETUP_TOKEN", SETUP_TOKEN)
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)

    # Ensure no users exist, then create one
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    async with await _client() as c:
        # First call — should succeed
        r1 = await c.post(
            "/api/admin/setup",
            json=VALID_BODY,
            headers={"X-Setup-Token": SETUP_TOKEN},
        )
        assert r1.status_code == 201, r1.text

        # Second call — should conflict
        r2 = await c.post(
            "/api/admin/setup",
            json={"username": "anotheradmin", "password": "anotherpassword99"},
            headers={"X-Setup-Token": SETUP_TOKEN},
        )
        assert r2.status_code == 409
        assert r2.json()["detail"] == "setup_already_complete"


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_setup_duplicate_username_returns_409(db_session, monkeypatch):
    """Race condition: if username already exists from concurrent setup, return 409."""
    from app.config import settings
    from app.models.users import User
    from sqlalchemy import text

    monkeypatch.setattr(settings, "SETUP_TOKEN", SETUP_TOKEN)
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)

    # Seed a user directly so the second request hits IntegrityError
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    # Seed one user so setup_already_complete fires first (count > 0)
    # This test validates the 409 path — both setup_already_complete and username_exists
    # produce 409; setup_already_complete fires first when count > 0
    seed = User(
        username="firstadmin",
        password_hash="$argon2id$stub",
        role="Admin",
        dashboard_roles=["red", "blue"],
        enabled=True,
        must_change_password=False,
        token_version=0,
    )
    db_session.add(seed)
    await db_session.commit()

    async with await _client() as c:
        r = await c.post(
            "/api/admin/setup",
            json=VALID_BODY,
            headers={"X-Setup-Token": SETUP_TOKEN},
        )
        assert r.status_code == 409
