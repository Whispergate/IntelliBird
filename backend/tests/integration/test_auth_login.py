"""POST /api/auth/login happy + 401 invalid + 429 lockout + /me + /logout

Integration tests — AUTH-01/03. Activated by plan 09-03.

Requires: testcontainers (Postgres + Redis). Skipped gracefully when Docker unavailable.
"""
from __future__ import annotations

import os
import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Env defaults (must be set before any app import)
# ---------------------------------------------------------------------------
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _auth_disabled(monkeypatch):
    """Bypass AuthMiddleware for this module — tokens are still validated elsewhere."""
    from app.config import settings
    monkeypatch.setattr(settings, "AUTH_ENABLED", False, raising=False)


# pg_url / redis_url / db_session come from tests/integration/conftest.py
# (session-scoped; use the live testcontainer + alembic-applied schema).


@pytest_asyncio.fixture
async def redis_client(redis_url):
    import redis.asyncio as aioredis
    r = aioredis.from_url(redis_url)
    # Flush auth keys before each test
    for pattern in ("jwt:revoked:*", "login:fails:*", "login:locked:*"):
        keys = [k async for k in r.scan_iter(match=pattern)]
        if keys:
            await r.delete(*keys)
    yield r
    for pattern in ("jwt:revoked:*", "login:fails:*", "login:locked:*"):
        keys = [k async for k in r.scan_iter(match=pattern)]
        if keys:
            await r.delete(*keys)
    await r.aclose()


@pytest_asyncio.fixture
async def auth_client(db_session, redis_url):
    """HttpX test client for the auth router with overridden DB session."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.routers.auth import router
    from app.database import get_session
    from app.config import settings

    app = FastAPI()
    app.include_router(router, prefix="")

    async def override_session() -> AsyncIterator:
        yield db_session

    app.dependency_overrides[get_session] = override_session

    # Patch redis to use test container
    import app.routers.auth as auth_module
    original_redis = auth_module._redis_client

    async def test_redis_client():
        import redis.asyncio as aioredis
        return aioredis.from_url(redis_url)

    auth_module._redis_client = test_redis_client

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    auth_module._redis_client = original_redis


@pytest_asyncio.fixture
async def admin_user(db_session, argon2_fast):
    """Seed an Admin user for test use."""
    from app.models.users import User
    from app.security.passwords import hash_password

    u = User(
        id=uuid.uuid4(),
        username="test-admin",
        password_hash=hash_password("correct-password-12"),
        oidc_sub=None,
        role="Admin",
        dashboard_roles=["red", "blue"],
        enabled=True,
        must_change_password=False,
        token_version=0,
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    yield u
    await db_session.delete(u)
    await db_session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_happy_path(auth_client, admin_user):
    r = await auth_client.post("/auth/login", json={
        "username": "test-admin",
        "password": "correct-password-12",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["expires_in"] == 900
    assert body["user"]["username"] == "test-admin"
    assert body["user"]["role"] == "Admin"
    assert "Set-Cookie" in r.headers


@pytest.mark.asyncio
async def test_login_sets_refresh_cookie_httponly(auth_client, admin_user):
    r = await auth_client.post("/auth/login", json={
        "username": "test-admin",
        "password": "correct-password-12",
    })
    assert r.status_code == 200
    cookie_header = r.headers.get("Set-Cookie", "")
    assert "refresh_token" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "SameSite=lax" in cookie_header or "samesite=lax" in cookie_header.lower()


@pytest.mark.asyncio
async def test_login_invalid_password_401(auth_client, admin_user):
    r = await auth_client.post("/auth/login", json={
        "username": "test-admin",
        "password": "wrong-password-here",
    })
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid_credentials"


@pytest.mark.asyncio
async def test_login_nonexistent_user_401(auth_client):
    """Non-existent user must return 401 (same code as wrong password — PITFALL 7)."""
    r = await auth_client.post("/auth/login", json={
        "username": "no-such-user",
        "password": "doesnt-matter-12",
    })
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid_credentials"


@pytest.mark.asyncio
async def test_login_disabled_user_403(auth_client, db_session, admin_user):
    from sqlalchemy import update
    from app.models.users import User
    await db_session.execute(
        update(User).where(User.id == admin_user.id).values(enabled=False)
    )
    await db_session.commit()
    r = await auth_client.post("/auth/login", json={
        "username": "test-admin",
        "password": "correct-password-12",
    })
    # Restore
    await db_session.execute(
        update(User).where(User.id == admin_user.id).values(enabled=True)
    )
    await db_session.commit()
    assert r.status_code == 403
    assert r.json()["detail"] == "user_disabled"


@pytest.mark.asyncio
async def test_login_lockout_after_5_fails_returns_429(auth_client, admin_user, redis_client):
    """5 consecutive failures must lock the account."""
    for _ in range(5):
        r = await auth_client.post("/auth/login", json={
            "username": "test-admin",
            "password": "wrong-12",
        })
    # 6th attempt should be 429
    r = await auth_client.post("/auth/login", json={
        "username": "test-admin",
        "password": "wrong-12",
    })
    assert r.status_code == 429
    assert "Retry-After" in r.headers


@pytest.mark.asyncio
async def test_login_success_clears_fails_counter(auth_client, admin_user, redis_client):
    """Successful login must clear the fails counter."""
    # Record 2 failures
    for _ in range(2):
        await auth_client.post("/auth/login", json={
            "username": "test-admin",
            "password": "wrong",
        })
    # Successful login
    r = await auth_client.post("/auth/login", json={
        "username": "test-admin",
        "password": "correct-password-12",
    })
    assert r.status_code == 200
    # Counter should be gone
    fails_key = f"login:fails:test-admin"
    count = await redis_client.get(fails_key)
    assert count is None


@pytest.mark.asyncio
async def test_me_returns_user_shape(auth_client, admin_user):
    from app.security.jwt import mint_access_token
    from app.config import settings
    token, _ = mint_access_token(
        str(admin_user.id), admin_user.role,
        list(admin_user.dashboard_roles or []), admin_user.token_version,
        settings.JWT_SIGNING_KEY,
    )
    # We need to mock require_auth since AUTH_ENABLED=False bypasses middleware
    # but /me uses Depends(require_auth). Inject user via override.
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.routers.auth import router
    from app.database import get_session
    from app.middleware.auth import require_auth
    from app.security.jwt import AuthUser

    test_user = AuthUser(
        id=str(admin_user.id),
        role=admin_user.role,
        dashboard_roles=list(admin_user.dashboard_roles or []),
        jti="test-jti",
        token_version=admin_user.token_version,
    )

    app = FastAPI()
    app.include_router(router, prefix="")

    async def override_session():
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
        from app.database import engine
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as s:
            yield s

    def override_require_auth():
        return test_user

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_auth] = override_require_auth

    # Point DB at our test container
    import app.database as db_module
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from app.config import settings

    test_engine = create_async_engine(settings.DATABASE_URL, future=True)
    test_factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)

    async def final_session():
        async with test_factory() as s:
            yield s

    app.dependency_overrides[get_session] = final_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/auth/me")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["username"] == "test-admin"
        assert body["role"] == "Admin"
        assert "dashboard_roles" in body
        assert "must_change_password" in body

    await test_engine.dispose()


@pytest.mark.asyncio
async def test_logout_revokes_access_jti(auth_client, admin_user, redis_client):
    """Logout must blocklist the access token JTI."""
    from app.security.jwt import mint_access_token, AuthUser
    from app.config import settings
    from app.middleware.auth import require_auth

    jti_str = str(uuid.uuid4())
    # Build a minimal app with require_auth overridden
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.routers.auth import router
    from app.database import get_session

    test_user = AuthUser(
        id=str(admin_user.id),
        role=admin_user.role,
        dashboard_roles=list(admin_user.dashboard_roles or []),
        jti=jti_str,
        token_version=0,
    )

    test_engine = None
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    test_engine = create_async_engine(settings.DATABASE_URL, future=True)
    test_factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)

    async def final_session():
        async with test_factory() as s:
            yield s

    import app.routers.auth as auth_module
    original_redis = auth_module._redis_client

    async def test_redis():
        import redis.asyncio as aioredis
        return aioredis.from_url(settings.REDIS_URL)

    auth_module._redis_client = test_redis

    app = FastAPI()
    app.include_router(router, prefix="")
    app.dependency_overrides[get_session] = final_session
    app.dependency_overrides[require_auth] = lambda: test_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/auth/logout")
        assert r.status_code == 204

    # Check JTI is in blocklist
    revoked = await redis_client.exists(f"jwt:revoked:{jti_str}")
    assert revoked == 1

    auth_module._redis_client = original_redis
    if test_engine:
        await test_engine.dispose()
