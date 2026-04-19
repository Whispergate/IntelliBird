"""INFRA-03/04: SystemStatusResponse.decrypt_check + auth_enabled wired from settings."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
os.environ.setdefault("SECRET_KEY", "a" * 64)
os.environ.setdefault("REDIS_URL", "redis://r:6379/0")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

import app.state as state_module  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402


async def _client():
    return AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://t")


@pytest.mark.asyncio
async def test_auth_enabled_wired_from_settings_false(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)
    async with await _client() as c:
        r = await c.get("/api/system/status")
        assert r.status_code == 200
        assert r.json()["auth_enabled"] is False


@pytest.mark.asyncio
async def test_auth_enabled_wired_from_settings_true(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    async with await _client() as c:
        r = await c.get("/api/system/status")
        assert r.status_code == 200
        assert r.json()["auth_enabled"] is True


@pytest.mark.asyncio
async def test_decrypt_check_default_unknown(monkeypatch) -> None:
    monkeypatch.setattr(state_module, "decrypt_check", "unknown")
    async with await _client() as c:
        r = await c.get("/api/system/status")
        body = r.json()
        assert body["decrypt_check"] == "unknown"


@pytest.mark.asyncio
async def test_decrypt_check_ok(monkeypatch) -> None:
    monkeypatch.setattr(state_module, "decrypt_check", "ok")
    async with await _client() as c:
        r = await c.get("/api/system/status")
        assert r.json()["decrypt_check"] == "ok"


@pytest.mark.asyncio
async def test_decrypt_check_failed_warning_text(monkeypatch) -> None:
    monkeypatch.setattr(state_module, "decrypt_check", "failed")
    async with await _client() as c:
        r = await c.get("/api/system/status")
        body = r.json()
        assert body["decrypt_check"] == "failed"
        warning = body["warning"]
        assert warning is not None
        assert "POST /api/admin/rekey-credentials" in warning
        assert "REKEY_FROM_SECRET" in warning


@pytest.mark.asyncio
async def test_decrypt_failure_takes_precedence_over_host_warning(monkeypatch) -> None:
    monkeypatch.setattr(state_module, "decrypt_check", "failed")
    monkeypatch.setattr(settings, "HOST", "0.0.0.0")  # would trigger host warning
    async with await _client() as c:
        r = await c.get("/api/system/status")
        warning = r.json()["warning"]
        assert "REKEY_FROM_SECRET" in warning  # decrypt warning won
        assert "exposed beyond loopback" not in warning  # host warning lost
