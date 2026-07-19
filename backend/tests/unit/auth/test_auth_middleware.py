"""AuthMiddleware unit tests - AUTH-02, AUTH-03."""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@h/d")
os.environ.setdefault("SECRET_KEY", "b" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "a" * 64)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest  # noqa: E402
from fastapi import Request  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.security.jwt import mint_access_token, mint_refresh_token  # noqa: E402


@pytest.fixture
def app_with_auth(monkeypatch):
    """Build a minimal FastAPI app with AuthMiddleware attached."""
    from fastapi import FastAPI
    from app.middleware.auth import AuthMiddleware
    from app.config import settings
    monkeypatch.setattr(settings, "AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "JWT_SIGNING_KEY", "a" * 64, raising=False)

    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/protected")
    async def protected(request: Request):
        return {"id": request.state.user.id, "role": request.state.user.role}

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return app


@pytest.mark.asyncio
async def test_exempt_path_no_token(app_with_auth):
    async with AsyncClient(transport=ASGITransport(app_with_auth), base_url="http://t") as c:
        r = await c.get("/healthz")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_missing_authorization_returns_401(app_with_auth):
    async with AsyncClient(transport=ASGITransport(app_with_auth), base_url="http://t") as c:
        r = await c.get("/protected")
        assert r.status_code == 401
        assert r.json()["detail"] == "invalid_token"


@pytest.mark.asyncio
async def test_non_bearer_returns_401(app_with_auth):
    async with AsyncClient(transport=ASGITransport(app_with_auth), base_url="http://t") as c:
        r = await c.get("/protected", headers={"Authorization": "Basic YWRtaW46"})
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_rejected(app_with_auth):
    token, _ = mint_refresh_token(str(uuid.uuid4()), "Admin", ["red"], 0, "a" * 64)
    async with AsyncClient(transport=ASGITransport(app_with_auth), base_url="http://t") as c:
        r = await c.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_tampered_token_returns_401(app_with_auth):
    token, _ = mint_access_token(str(uuid.uuid4()), "Admin", ["red"], 0, "a" * 64)
    async with AsyncClient(transport=ASGITransport(app_with_auth), base_url="http://t") as c:
        r = await c.get("/protected", headers={"Authorization": f"Bearer {token[:-4]}AAAA"})
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_token_version_mismatch_returns_401(app_with_auth):
    """Claim token_version=0; DB says 5 -> revoked."""
    user_id = str(uuid.uuid4())
    token, _ = mint_access_token(user_id, "Admin", ["red"], 0, "a" * 64)
    with patch("app.middleware.auth._get_cached_token_version", new=AsyncMock(return_value=5)):
        async with AsyncClient(transport=ASGITransport(app_with_auth), base_url="http://t") as c:
            r = await c.get("/protected", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 401
            assert r.json()["detail"] == "revoked_token"


@pytest.mark.asyncio
async def test_jti_blocklist_returns_401(app_with_auth):
    user_id = str(uuid.uuid4())
    token, _ = mint_access_token(user_id, "Admin", ["red"], 0, "a" * 64)
    with patch("app.middleware.auth._get_cached_token_version", new=AsyncMock(return_value=0)), \
         patch("app.middleware.auth._is_jti_revoked", new=AsyncMock(return_value=True)):
        async with AsyncClient(transport=ASGITransport(app_with_auth), base_url="http://t") as c:
            r = await c.get("/protected", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 401
            assert r.json()["detail"] == "revoked_token"


@pytest.mark.asyncio
async def test_redis_down_returns_503(app_with_auth):
    """PITFALL 3 - fail-closed on Redis connection error."""
    user_id = str(uuid.uuid4())
    token, _ = mint_access_token(user_id, "Admin", ["red"], 0, "a" * 64)
    with patch("app.middleware.auth._get_cached_token_version", new=AsyncMock(return_value=0)), \
         patch("app.middleware.auth._is_jti_revoked", new=AsyncMock(side_effect=RuntimeError("auth_infra_down"))):
        async with AsyncClient(transport=ASGITransport(app_with_auth), base_url="http://t") as c:
            r = await c.get("/protected", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 503
            assert r.json()["detail"] == "auth_infra_down"


@pytest.mark.asyncio
async def test_valid_token_populates_request_state(app_with_auth):
    user_id = str(uuid.uuid4())
    token, _ = mint_access_token(user_id, "Analyst", ["blue"], 0, "a" * 64)
    with patch("app.middleware.auth._get_cached_token_version", new=AsyncMock(return_value=0)), \
         patch("app.middleware.auth._is_jti_revoked", new=AsyncMock(return_value=False)):
        async with AsyncClient(transport=ASGITransport(app_with_auth), base_url="http://t") as c:
            r = await c.get("/protected", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200
            assert r.json() == {"id": user_id, "role": "Analyst"}


@pytest.mark.asyncio
async def test_expired_token_has_refresh_required_header(app_with_auth, monkeypatch):
    import time as _time
    int(_time.time())
    # Mint with normal time, then make time jump forward so token appears expired
    token, _ = mint_access_token(str(uuid.uuid4()), "Admin", ["red"], 0, "a" * 64)
    # Patch jwt decode to raise ExpiredSignatureError
    import jwt as pyjwt
    with patch("app.middleware.auth.decode_token", side_effect=pyjwt.ExpiredSignatureError("expired")):
        async with AsyncClient(transport=ASGITransport(app_with_auth), base_url="http://t") as c:
            r = await c.get("/protected", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 401
            assert r.json()["detail"] == "expired_token"
            assert r.headers.get("X-Refresh-Required") == "true"


def test_exempt_paths_contents():
    """EXEMPT_PATHS MUST include exactly the 9 pre-auth paths (8 + setup-status)."""
    from app.middleware.auth import EXEMPT_PATHS
    assert EXEMPT_PATHS == frozenset({
        "/healthz",
        "/api/system/status",
        "/api/system/setup-status",
        "/api/admin/rekey-credentials",
        "/api/admin/setup",
        "/api/auth/login",
        "/api/auth/refresh",
        "/api/auth/oidc/login",
        "/api/auth/oidc/callback",
    })
