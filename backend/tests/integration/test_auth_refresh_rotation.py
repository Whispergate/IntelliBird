"""/refresh rotates JTI + old JTI blocklisted + reuse detection bumps token_version

Integration tests — AUTH-03/M-1. Activated by plan 09-03.

Requires: testcontainers (Postgres + Redis). Skipped gracefully when Docker unavailable.
"""
from __future__ import annotations

import os
import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration

os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)


# ---------------------------------------------------------------------------
# Minimal inline fixtures (mirrors test_auth_login.py pattern but lighter)
# These tests use the router directly with a real DB + Redis container.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def full_client(pg_container, redis_container, argon2_fast):
    """Stand up a minimal FastAPI app with the auth router + real DB + Redis."""
    # Resolve URLs
    pg_url = pg_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    ).replace("postgresql://", "postgresql+asyncpg://")
    redis_host = redis_container.get_container_host_ip()
    redis_port = redis_container.get_exposed_port(6379)
    redis_url = f"redis://{redis_host}:{redis_port}/10"

    from app.config import settings
    settings.DATABASE_URL = pg_url  # type: ignore[assignment]
    settings.REDIS_URL = redis_url  # type: ignore[assignment]
    settings.JWT_SIGNING_KEY = "j" * 64  # type: ignore[assignment]
    os.environ["DATABASE_URL"] = pg_url
    os.environ["REDIS_URL"] = redis_url

    # Run migrations
    import alembic.config
    import alembic.command
    alembic_ini = os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini")
    alembic_cfg = alembic.config.Config(alembic_ini)
    alembic_cfg.set_main_option("script_location", "alembic")
    alembic_cfg.set_main_option(
        "sqlalchemy.url",
        pg_url.replace("postgresql+asyncpg://", "postgresql://"),
    )
    alembic.command.upgrade(alembic_cfg, "head")

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    engine = create_async_engine(pg_url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # Seed a test user
    from app.models.users import User
    from app.security.passwords import hash_password
    import redis.asyncio as aioredis

    test_user_id = uuid.uuid4()
    async with factory() as s:
        u = User(
            id=test_user_id,
            username="refresh-test-user",
            password_hash=hash_password("test-password-12"),
            oidc_sub=None,
            role="Analyst",
            dashboard_roles=["blue"],
            enabled=True,
            must_change_password=False,
            token_version=0,
        )
        s.add(u)
        await s.commit()

    # Build app
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.routers.auth import router
    from app.database import get_session
    import app.routers.auth as auth_module

    orig_redis = auth_module._redis_client

    async def test_redis():
        return aioredis.from_url(redis_url)

    auth_module._redis_client = test_redis

    app = FastAPI()
    app.include_router(router, prefix="")

    async def override_session():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, factory, test_user_id, redis_url

    auth_module._redis_client = orig_redis
    # Cleanup
    async with factory() as s:
        row = await s.get(User, test_user_id)
        if row:
            await s.delete(row)
            await s.commit()
    await engine.dispose()

    # Flush redis
    r = aioredis.from_url(redis_url)
    for pat in ("jwt:revoked:*", "login:fails:*", "login:locked:*"):
        keys = [k async for k in r.scan_iter(match=pat)]
        if keys:
            await r.delete(*keys)
    await r.aclose()


@pytest.mark.asyncio
async def test_refresh_happy_path_new_pair_issued(full_client):
    """Refresh with valid cookie returns a new access_token + new refresh_token."""
    client, factory, user_id, redis_url = full_client
    # Login to get initial pair
    r = await client.post("/login", json={
        "username": "refresh-test-user",
        "password": "test-password-12",
    })
    assert r.status_code == 200, r.text
    access_1 = r.json()["access_token"]

    # POST /refresh — httpx stores the Set-Cookie automatically
    r2 = await client.post("/refresh")
    assert r2.status_code == 200, r2.text
    access_2 = r2.json()["access_token"]
    assert access_1 != access_2  # new JTI issued


@pytest.mark.asyncio
async def test_refresh_old_jti_blocklisted_before_new_pair_returned(full_client):
    """Old refresh JTI must be in Redis blocklist after rotation."""
    import redis.asyncio as aioredis
    client, factory, user_id, redis_url = full_client

    r = await client.post("/login", json={
        "username": "refresh-test-user",
        "password": "test-password-12",
    })
    assert r.status_code == 200
    refresh_cookie = r.cookies.get("refresh_token")
    assert refresh_cookie

    # Decode the old refresh JTI
    import jwt as pyjwt
    old_claims = pyjwt.decode(refresh_cookie, options={"verify_signature": False})
    old_jti = old_claims["jti"]

    # Rotate
    r2 = await client.post("/refresh")
    assert r2.status_code == 200

    # Old JTI must be revoked
    r_client = aioredis.from_url(redis_url)
    revoked = await r_client.exists(f"jwt:revoked:{old_jti}")
    await r_client.aclose()
    assert revoked == 1


@pytest.mark.asyncio
async def test_refresh_reuse_detection_bumps_token_version(full_client):
    """Presenting a previously-rotated (revoked) refresh token bumps token_version."""
    import redis.asyncio as aioredis
    from sqlalchemy import select
    from app.models.users import User

    client, factory, user_id, redis_url = full_client

    # Login
    r = await client.post("/login", json={
        "username": "refresh-test-user",
        "password": "test-password-12",
    })
    assert r.status_code == 200
    old_refresh = r.cookies.get("refresh_token")

    # First refresh — rotates old cookie
    r2 = await client.post("/refresh")
    assert r2.status_code == 200

    # Manually inject the old (now revoked) refresh cookie and POST /refresh again
    old_client_kwargs = {"cookies": {"refresh_token": old_refresh}}
    r3 = await client.post("/refresh", cookies={"refresh_token": old_refresh})
    assert r3.status_code == 401
    assert r3.json()["detail"] == "revoked_token"
    assert r3.headers.get("X-Session-Revoked") == "reuse_detected"

    # token_version must have been bumped
    async with factory() as s:
        u = await s.get(User, user_id)
        assert u is not None
        assert u.token_version >= 1


@pytest.mark.asyncio
async def test_refresh_with_access_token_type_returns_401(full_client):
    """Posting an access token as refresh cookie must return 401."""
    from app.security.jwt import mint_access_token
    client, _, user_id, _ = full_client

    access, _ = mint_access_token(str(user_id), "Analyst", ["blue"], 0, "j" * 64)
    r = await client.post("/refresh", cookies={"refresh_token": access})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_refresh_no_cookie_returns_401(full_client):
    """Missing refresh cookie must return 401."""
    client, _, _, _ = full_client
    # Clear cookies explicitly
    client.cookies.clear()
    r = await client.post("/refresh")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_change_password_bumps_token_version(full_client):
    """change-password must bump token_version and return a new token pair."""
    from app.middleware.auth import require_auth
    from app.security.jwt import AuthUser
    from app.models.users import User

    client, factory, user_id, _ = full_client

    # Read current token_version
    async with factory() as s:
        u = await s.get(User, user_id)
        old_tv = u.token_version

    # Override require_auth to inject the test user without a real JWT
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.routers.auth import router
    from app.database import get_session
    import app.routers.auth as auth_module

    test_auth_user = AuthUser(
        id=str(user_id), role="Analyst",
        dashboard_roles=["blue"], jti="test", token_version=old_tv,
    )

    mini_app = FastAPI()
    mini_app.include_router(router, prefix="")

    async def override_session():
        async with factory() as s:
            yield s

    mini_app.dependency_overrides[get_session] = override_session
    mini_app.dependency_overrides[require_auth] = lambda: test_auth_user

    orig_redis = auth_module._redis_client
    from app.config import settings
    import redis.asyncio as aioredis

    async def test_redis():
        return aioredis.from_url(settings.REDIS_URL)

    auth_module._redis_client = test_redis

    async with AsyncClient(transport=ASGITransport(app=mini_app), base_url="http://t") as c:
        r = await c.post("/change-password", json={
            "current_password": "test-password-12",
            "new_password": "new-password-that-is-long-enough",
        })
        assert r.status_code == 200, r.text
        assert "access_token" in r.json()

    auth_module._redis_client = orig_redis

    # Verify token_version bumped
    async with factory() as s:
        u = await s.get(User, user_id)
        assert u.token_version == old_tv + 1

    # Restore password for subsequent tests
    from app.security.passwords import hash_password
    async with factory() as s:
        u = await s.get(User, user_id)
        u.password_hash = hash_password("test-password-12")
        u.token_version = 0
        await s.commit()


@pytest.mark.asyncio
async def test_change_password_same_as_current_returns_400(full_client):
    from app.middleware.auth import require_auth
    from app.security.jwt import AuthUser
    from app.models.users import User
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.routers.auth import router
    from app.database import get_session
    import app.routers.auth as auth_module
    from app.config import settings
    import redis.asyncio as aioredis

    client, factory, user_id, _ = full_client
    async with factory() as s:
        u = await s.get(User, user_id)
        tv = u.token_version

    test_auth_user = AuthUser(
        id=str(user_id), role="Analyst",
        dashboard_roles=["blue"], jti="test", token_version=tv,
    )

    mini_app = FastAPI()
    mini_app.include_router(router, prefix="")

    async def override_session():
        async with factory() as s:
            yield s

    mini_app.dependency_overrides[get_session] = override_session
    mini_app.dependency_overrides[require_auth] = lambda: test_auth_user

    orig_redis = auth_module._redis_client

    async def test_redis():
        return aioredis.from_url(settings.REDIS_URL)

    auth_module._redis_client = test_redis

    async with AsyncClient(transport=ASGITransport(app=mini_app), base_url="http://t") as c:
        r = await c.post("/change-password", json={
            "current_password": "test-password-12",
            "new_password": "test-password-12",
        })
        assert r.status_code == 400
        assert r.json()["detail"] == "new_password_same_as_current"

    auth_module._redis_client = orig_redis


@pytest.mark.asyncio
async def test_change_password_too_short_returns_422(full_client):
    from app.middleware.auth import require_auth
    from app.security.jwt import AuthUser
    from app.models.users import User
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.routers.auth import router
    from app.database import get_session

    client, factory, user_id, _ = full_client
    async with factory() as s:
        u = await s.get(User, user_id)
        tv = u.token_version

    test_auth_user = AuthUser(
        id=str(user_id), role="Analyst",
        dashboard_roles=["blue"], jti="test", token_version=tv,
    )

    mini_app = FastAPI()
    mini_app.include_router(router, prefix="")

    async def override_session():
        async with factory() as s:
            yield s

    mini_app.dependency_overrides[get_session] = override_session
    mini_app.dependency_overrides[require_auth] = lambda: test_auth_user

    async with AsyncClient(transport=ASGITransport(app=mini_app), base_url="http://t") as c:
        r = await c.post("/change-password", json={
            "current_password": "test-password-12",
            "new_password": "short",  # < 12 chars
        })
        assert r.status_code == 422
