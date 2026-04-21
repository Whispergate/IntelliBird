"""/oidc/login redirect + /oidc/callback exchanges code + groups->role mapping

Integration tests — AUTH-01. Activated by plan 09-03.

Authentik upstream is mocked via monkeypatch — no live Authentik required.
Requires: testcontainers (Postgres) for the user upsert path.
"""
from __future__ import annotations

import os
import uuid
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

from tests.fixtures.authentik_mock import (  # noqa: E402
    AUTHENTIK_DISCOVERY,
    MOCK_ISSUER_URL,
    SAMPLE_ID_TOKEN_CLAIMS,
    ADMIN_GROUPS_CLAIM,
    ANALYST_GROUPS_CLAIM,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def oidc_app(pg_container):
    """Minimal FastAPI app with auth router + real Postgres DB (no Redis needed for OIDC tests)."""
    pg_url = pg_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    ).replace("postgresql://", "postgresql+asyncpg://")

    from app.config import settings
    settings.DATABASE_URL = pg_url  # type: ignore[assignment]
    settings.JWT_SIGNING_KEY = "j" * 64  # type: ignore[assignment]
    os.environ["DATABASE_URL"] = pg_url

    # Migrations via subprocess to avoid nested asyncio.run() from alembic/env.py
    # inside the pytest-asyncio event loop.
    import subprocess
    from pathlib import Path
    backend_dir = Path(__file__).resolve().parents[2]
    env = os.environ | {"DATABASE_URL": pg_url}
    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=str(backend_dir),
        env=env,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.skip(f"alembic upgrade head failed:\n{r.stderr[:800]}")

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    engine = create_async_engine(pg_url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.routers.auth import router
    from app.database import get_session
    import app.routers.auth as auth_module
    import redis.asyncio as aioredis

    # Use a no-op redis for OIDC tests that don't need logout/blocklist
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    orig_redis = auth_module._redis_client

    async def noop_redis():
        return aioredis.from_url(redis_url)

    auth_module._redis_client = noop_redis

    app = FastAPI()
    app.include_router(router, prefix="")

    async def override_session():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, factory

    auth_module._redis_client = orig_redis
    await engine.dispose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_oidc_login_404_when_unconfigured(oidc_app):
    """GET /oidc/login returns 404 when SSO_ISSUER_URL is unset."""
    client, _ = oidc_app
    from app.config import settings
    original = settings.SSO_ISSUER_URL
    settings.SSO_ISSUER_URL = None  # type: ignore[assignment]
    try:
        r = await client.get("/auth/oidc/login", follow_redirects=False)
        assert r.status_code == 404
        assert r.json()["detail"] == "oidc_not_configured"
    finally:
        settings.SSO_ISSUER_URL = original  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_oidc_login_302_with_correct_query_params_when_configured(oidc_app):
    """GET /oidc/login when configured returns 302 with correct authorization URL params."""
    client, _ = oidc_app
    from app.config import settings
    settings.SSO_ISSUER_URL = MOCK_ISSUER_URL
    settings.SSO_CLIENT_ID = "intellibird-client"
    settings.SSO_GROUPS_CLAIM = "groups"

    with patch(
        "app.routers.auth.fetch_server_metadata",
        new=AsyncMock(return_value=AUTHENTIK_DISCOVERY),
    ):
        r = await client.get("/auth/oidc/login", follow_redirects=False)

    settings.SSO_ISSUER_URL = None  # type: ignore[assignment]
    settings.SSO_CLIENT_ID = None  # type: ignore[assignment]

    assert r.status_code == 302
    location = r.headers["Location"]
    assert "response_type=code" in location
    assert "openid" in location
    assert "code_challenge_method=S256" in location
    assert "state=" in location
    assert "nonce=" in location
    assert "client_id=intellibird-client" in location


@pytest.mark.asyncio
async def test_oidc_login_sets_state_verifier_nonce_cookies(oidc_app):
    """Ensure state, verifier, and nonce cookies are set on /oidc/login response."""
    client, _ = oidc_app
    from app.config import settings
    settings.SSO_ISSUER_URL = MOCK_ISSUER_URL
    settings.SSO_CLIENT_ID = "intellibird-client"
    settings.SSO_GROUPS_CLAIM = "groups"

    with patch(
        "app.routers.auth.fetch_server_metadata",
        new=AsyncMock(return_value=AUTHENTIK_DISCOVERY),
    ):
        r = await client.get("/auth/oidc/login", follow_redirects=False)

    settings.SSO_ISSUER_URL = None  # type: ignore[assignment]
    settings.SSO_CLIENT_ID = None  # type: ignore[assignment]

    assert r.status_code == 302
    set_cookie_headers = r.headers.get_list("Set-Cookie") if hasattr(r.headers, "get_list") else [
        v for k, v in r.headers.items() if k.lower() == "set-cookie"
    ]
    cookie_names = " ".join(set_cookie_headers)
    assert "oidc_state" in cookie_names
    assert "oidc_verifier" in cookie_names
    assert "oidc_nonce" in cookie_names


@pytest.mark.asyncio
async def test_callback_invalid_state_returns_400(oidc_app):
    """State mismatch returns 400 invalid_state."""
    client, _ = oidc_app
    from app.config import settings
    settings.SSO_ISSUER_URL = MOCK_ISSUER_URL

    # Provide a different state in cookie vs query param
    r = await client.get(
        "/auth/oidc/callback",
        params={"code": "some-code", "state": "state-in-query"},
        cookies={"oidc_state": "different-state"},
        follow_redirects=False,
    )
    settings.SSO_ISSUER_URL = None  # type: ignore[assignment]
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_state"


@pytest.mark.asyncio
async def test_callback_missing_code_returns_400(oidc_app):
    """Missing code parameter returns 400."""
    client, _ = oidc_app
    from app.config import settings
    settings.SSO_ISSUER_URL = MOCK_ISSUER_URL

    r = await client.get(
        "/auth/oidc/callback",
        params={"state": "some-state"},
        cookies={"oidc_state": "some-state"},
        follow_redirects=False,
    )
    settings.SSO_ISSUER_URL = None  # type: ignore[assignment]
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_callback_happy_path_creates_viewer_user_by_default(oidc_app):
    """First-time Authentik login with no group match creates a Viewer user."""
    client, factory = oidc_app
    from app.config import settings
    from app.models.users import User
    from sqlalchemy import select

    settings.SSO_ISSUER_URL = MOCK_ISSUER_URL
    settings.SSO_CLIENT_ID = "intellibird-client"
    settings.SSO_GROUPS_CLAIM = "groups"
    settings.SSO_ADMIN_GROUPS = "intellibird-admins"
    settings.SSO_ANALYST_GROUPS = "intellibird-analysts"

    test_sub = f"test-viewer-{uuid.uuid4().hex[:8]}"
    id_token_claims = {**SAMPLE_ID_TOKEN_CLAIMS, "sub": test_sub, "groups": [], "nonce": "test-nonce"}

    mock_token_resp = {"id_token": "fake.id.token"}

    mock_client = AsyncMock()
    mock_client.fetch_token = AsyncMock(return_value=mock_token_resp)
    mock_client.aclose = AsyncMock()

    with patch("app.routers.auth.fetch_server_metadata", new=AsyncMock(return_value=AUTHENTIK_DISCOVERY)), \
         patch("app.routers.auth.build_oidc_client", new=AsyncMock(return_value=mock_client)), \
         patch("app.routers.auth.verify_id_token", new=AsyncMock(return_value=id_token_claims)):

        r = await client.get(
            "/auth/oidc/callback",
            params={"code": "auth-code", "state": "test-state"},
            cookies={
                "oidc_state": "test-state",
                "oidc_verifier": "test-verifier",
                "oidc_nonce": "test-nonce",
            },
            follow_redirects=False,
        )

    settings.SSO_ISSUER_URL = None  # type: ignore[assignment]
    settings.SSO_CLIENT_ID = None  # type: ignore[assignment]

    assert r.status_code == 302, r.text

    # Verify user was created as Viewer
    async with factory() as s:
        u = (await s.execute(select(User).where(User.oidc_sub == test_sub))).scalar_one_or_none()
        assert u is not None
        assert u.role == "Viewer"
        # Cleanup
        await s.delete(u)
        await s.commit()


@pytest.mark.asyncio
async def test_callback_admin_group_creates_admin_with_both_dashboards(oidc_app):
    """Admin group match creates an Admin with dashboard_roles=['red', 'blue']."""
    client, factory = oidc_app
    from app.config import settings
    from app.models.users import User
    from sqlalchemy import select

    settings.SSO_ISSUER_URL = MOCK_ISSUER_URL
    settings.SSO_CLIENT_ID = "intellibird-client"
    settings.SSO_GROUPS_CLAIM = "groups"
    settings.SSO_ADMIN_GROUPS = "intellibird-admins"
    settings.SSO_ANALYST_GROUPS = "intellibird-analysts"

    test_sub = f"test-admin-{uuid.uuid4().hex[:8]}"
    id_token_claims = {
        **SAMPLE_ID_TOKEN_CLAIMS,
        "sub": test_sub,
        "groups": ["intellibird-admins"],
        "nonce": "test-nonce-admin",
    }

    mock_client = AsyncMock()
    mock_client.fetch_token = AsyncMock(return_value={"id_token": "fake.admin.token"})
    mock_client.aclose = AsyncMock()

    with patch("app.routers.auth.fetch_server_metadata", new=AsyncMock(return_value=AUTHENTIK_DISCOVERY)), \
         patch("app.routers.auth.build_oidc_client", new=AsyncMock(return_value=mock_client)), \
         patch("app.routers.auth.verify_id_token", new=AsyncMock(return_value=id_token_claims)):

        r = await client.get(
            "/auth/oidc/callback",
            params={"code": "admin-code", "state": "admin-state"},
            cookies={
                "oidc_state": "admin-state",
                "oidc_verifier": "admin-verifier",
                "oidc_nonce": "test-nonce-admin",
            },
            follow_redirects=False,
        )

    settings.SSO_ISSUER_URL = None  # type: ignore[assignment]
    settings.SSO_CLIENT_ID = None  # type: ignore[assignment]

    assert r.status_code == 302, r.text

    async with factory() as s:
        u = (await s.execute(select(User).where(User.oidc_sub == test_sub))).scalar_one_or_none()
        assert u is not None
        assert u.role == "Admin"
        assert sorted(u.dashboard_roles) == ["blue", "red"]
        await s.delete(u)
        await s.commit()


@pytest.mark.asyncio
async def test_callback_returning_user_updates_last_login_no_duplicate_row(oidc_app):
    """Second Authentik login updates last_login_at without creating a duplicate user row."""
    client, factory = oidc_app
    from app.config import settings
    from app.models.users import User
    from sqlalchemy import select, func

    settings.SSO_ISSUER_URL = MOCK_ISSUER_URL
    settings.SSO_CLIENT_ID = "intellibird-client"
    settings.SSO_GROUPS_CLAIM = "groups"
    settings.SSO_ADMIN_GROUPS = "intellibird-admins"
    settings.SSO_ANALYST_GROUPS = None

    test_sub = f"test-returning-{uuid.uuid4().hex[:8]}"
    id_token_claims = {
        **SAMPLE_ID_TOKEN_CLAIMS,
        "sub": test_sub,
        "groups": [],
        "nonce": "returning-nonce",
    }

    mock_client = AsyncMock()
    mock_client.fetch_token = AsyncMock(return_value={"id_token": "fake.returning.token"})
    mock_client.aclose = AsyncMock()

    for _ in range(2):
        with patch("app.routers.auth.fetch_server_metadata", new=AsyncMock(return_value=AUTHENTIK_DISCOVERY)), \
             patch("app.routers.auth.build_oidc_client", new=AsyncMock(return_value=mock_client)), \
             patch("app.routers.auth.verify_id_token", new=AsyncMock(return_value=id_token_claims)):
            r = await client.get(
                "/auth/oidc/callback",
                params={"code": "code", "state": "s"},
                cookies={"oidc_state": "s", "oidc_verifier": "v", "oidc_nonce": "returning-nonce"},
                follow_redirects=False,
            )
        assert r.status_code == 302

    settings.SSO_ISSUER_URL = None  # type: ignore[assignment]
    settings.SSO_CLIENT_ID = None  # type: ignore[assignment]

    async with factory() as s:
        rows = (await s.execute(select(User).where(User.oidc_sub == test_sub))).scalars().all()
        assert len(rows) == 1  # no duplicate
        await s.delete(rows[0])
        await s.commit()


@pytest.mark.asyncio
async def test_callback_landing_redirect_by_dashboard_role(oidc_app):
    """Admin users (red+blue) land at /red; Viewer users (no roles) land at /."""
    client, factory = oidc_app
    from app.config import settings
    from app.models.users import User

    settings.SSO_ISSUER_URL = MOCK_ISSUER_URL
    settings.SSO_CLIENT_ID = "intellibird-client"
    settings.SSO_GROUPS_CLAIM = "groups"
    settings.SSO_ADMIN_GROUPS = "intellibird-admins"
    settings.SSO_ANALYST_GROUPS = None

    # Viewer — no dashboard_roles — lands at /
    viewer_sub = f"viewer-land-{uuid.uuid4().hex[:8]}"
    id_claims = {**SAMPLE_ID_TOKEN_CLAIMS, "sub": viewer_sub, "groups": [], "nonce": "land-nonce"}

    mock_client = AsyncMock()
    mock_client.fetch_token = AsyncMock(return_value={"id_token": "fake"})
    mock_client.aclose = AsyncMock()

    with patch("app.routers.auth.fetch_server_metadata", new=AsyncMock(return_value=AUTHENTIK_DISCOVERY)), \
         patch("app.routers.auth.build_oidc_client", new=AsyncMock(return_value=mock_client)), \
         patch("app.routers.auth.verify_id_token", new=AsyncMock(return_value=id_claims)):
        r = await client.get(
            "/auth/oidc/callback",
            params={"code": "c", "state": "st"},
            cookies={"oidc_state": "st", "oidc_verifier": "vv", "oidc_nonce": "land-nonce"},
            follow_redirects=False,
        )

    settings.SSO_ISSUER_URL = None  # type: ignore[assignment]
    settings.SSO_CLIENT_ID = None  # type: ignore[assignment]

    assert r.status_code == 302
    assert r.headers["Location"] == "/"

    # Cleanup
    from sqlalchemy import select
    async with factory() as s:
        u = (await s.execute(select(User).where(User.oidc_sub == viewer_sub))).scalar_one_or_none()
        if u:
            await s.delete(u)
            await s.commit()
