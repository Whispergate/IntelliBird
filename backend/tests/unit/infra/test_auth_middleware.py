"""INFRA-04: AuthMiddleware stub (pass-through vs 401)."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
os.environ.setdefault("SECRET_KEY", "a" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "a" * 64)  # Phase 9 required field
os.environ.setdefault("REDIS_URL", "redis://r:6379/0")

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

from app.config import settings  # noqa: E402
from app.middleware.auth import AuthMiddleware, EXEMPT_PATHS  # noqa: E402


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/any-path")
    async def any_path() -> dict[str, str]:
        return {"reached": "handler"}

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/system/status")
    async def status() -> dict[str, str]:
        return {"auth_enabled": "false"}

    @app.post("/api/admin/rekey-credentials")
    async def rekey() -> dict[str, str]:
        return {"reached": "handler"}

    return app


@pytest.mark.asyncio
async def test_exempt_paths_contents() -> None:
    # Phase 9 extended EXEMPT_PATHS from 3 to 8 entries (auth endpoints + setup)
    assert EXEMPT_PATHS == frozenset({
        "/healthz",
        "/api/system/status",
        "/api/admin/rekey-credentials",
        "/api/admin/setup",
        "/api/auth/login",
        "/api/auth/refresh",
        "/api/auth/oidc/login",
        "/api/auth/oidc/callback",
    })


@pytest.mark.asyncio
async def test_auth_disabled_passthrough_returns_200(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/any-path")
        assert r.status_code == 200
        assert r.json() == {"reached": "handler"}


@pytest.mark.asyncio
async def test_auth_enabled_blocks_with_401(monkeypatch) -> None:
    # Phase 9: real JWT middleware returns "invalid_token" (no bearer header provided)
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/any-path")
        assert r.status_code == 401
        assert r.json() == {"detail": "invalid_token"}


@pytest.mark.asyncio
async def test_auth_enabled_exempts_healthz(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/healthz")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_auth_enabled_exempts_system_status(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/system/status")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_auth_enabled_exempts_rekey_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/admin/rekey-credentials")
        assert r.status_code == 200


def test_middleware_class_hierarchy() -> None:
    assert issubclass(AuthMiddleware, BaseHTTPMiddleware)
