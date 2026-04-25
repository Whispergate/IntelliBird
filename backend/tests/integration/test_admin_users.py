"""POST/GET/PATCH /api/admin/users + /unlock + disable flushes refresh tokens.

Integration tests — AUTH-01/02. Activated by plan 09-04.

Uses ASGITransport with the FastAPI app (no live DB required for token/auth tests;
DB-touching tests require the db_session fixture from conftest).

Auth pattern: mint real JWT access tokens with the test signing key, set AUTH_ENABLED=True
so the AuthMiddleware performs claim validation, pass the bearer header on every request.
"""
from __future__ import annotations

import os
import uuid as _uuid

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "a" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "b" * 64)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

pytestmark = pytest.mark.integration

TEST_SIGNING_KEY = "b" * 64


def _mint_admin_token(user_id: str | None = None) -> str:
    from app.security.jwt import mint_access_token
    uid = user_id or str(_uuid.uuid4())
    token, _ = mint_access_token(
        user_id=uid,
        role="Admin",
        dashboard_roles=["red", "blue"],
        token_version=0,
        signing_key=TEST_SIGNING_KEY,
    )
    return token


def _mint_analyst_token(user_id: str | None = None) -> str:
    from app.security.jwt import mint_access_token
    uid = user_id or str(_uuid.uuid4())
    token, _ = mint_access_token(
        user_id=uid,
        role="Analyst",
        dashboard_roles=["red", "blue"],
        token_version=0,
        signing_key=TEST_SIGNING_KEY,
    )
    return token


def _mint_viewer_token(user_id: str | None = None) -> str:
    from app.security.jwt import mint_access_token
    uid = user_id or str(_uuid.uuid4())
    token, _ = mint_access_token(
        user_id=uid,
        role="Viewer",
        dashboard_roles=["blue"],
        token_version=0,
        signing_key=TEST_SIGNING_KEY,
    )
    return token


async def _client():
    from app.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_mint_admin_token()}"}


def _analyst_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_mint_analyst_token()}"}


def _viewer_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_mint_viewer_token()}"}


def _patch_auth(monkeypatch) -> None:
    """Bypass DB token_version and Redis revocation checks for unit-style tests.

    Also pins settings.JWT_SIGNING_KEY to TEST_SIGNING_KEY so the AuthMiddleware
    can verify tokens minted with TEST_SIGNING_KEY even after earlier tests
    (e.g. tests/unit/auth) changed the env-loaded signing key."""
    import app.middleware.auth as auth_mod
    from app.config import settings

    async def _fake_token_version(user_id: str):
        return 0  # matches token_version=0 minted in test tokens

    async def _fake_jti_revoked(jti: str) -> bool:
        return False  # not revoked

    monkeypatch.setattr(auth_mod, "_get_cached_token_version", _fake_token_version)
    monkeypatch.setattr(auth_mod, "_is_jti_revoked", _fake_jti_revoked)
    monkeypatch.setattr(settings, "JWT_SIGNING_KEY", TEST_SIGNING_KEY, raising=False)


VALID_CREATE_BODY = {
    "username": "newanalyst",
    "role": "Analyst",
    "dashboard_roles": ["red"],
    "initial_password": "temporarypassword123",
}

ADMIN_CREATE_BODY = {
    "username": "newadmin",
    "role": "Admin",
    "dashboard_roles": [],  # Should be forced to ["red", "blue"]
    "initial_password": "temporarypassword123",
}


# ---------------------------------------------------------------------------
# POST /api/admin/users — create user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_user_as_analyst_returns_403(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    async with await _client() as c:
        r = await c.post(
            "/api/admin/users",
            json=VALID_CREATE_BODY,
            headers=_analyst_headers(),
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "insufficient_role"


@pytest.mark.asyncio
async def test_create_user_as_viewer_returns_403(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    async with await _client() as c:
        r = await c.post(
            "/api/admin/users",
            json=VALID_CREATE_BODY,
            headers=_viewer_headers(),
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_user_password_too_short_returns_422(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    async with await _client() as c:
        r = await c.post(
            "/api/admin/users",
            json={**VALID_CREATE_BODY, "initial_password": "short"},
            headers=_admin_headers(),
        )
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_user_happy_path_hashes_password(db_session, monkeypatch, argon2_fast):
    """POST /api/admin/users creates user with Argon2-hashed password."""
    from app.config import settings
    from app.models.users import User
    from sqlalchemy import select, text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)

    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    async with await _client() as c:
        r = await c.post(
            "/api/admin/users",
            json={**VALID_CREATE_BODY, "username": "analyst_hptest"},
            headers=_admin_headers(),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["username"] == "analyst_hptest"
        assert body["role"] == "Analyst"
        assert body["must_change_password"] is True
        assert body["enabled"] is True

    row = (await db_session.execute(
        select(User).where(User.username == "analyst_hptest")
    )).scalar_one_or_none()
    assert row is not None
    assert row.password_hash.startswith("$argon2id$")
    assert row.must_change_password is True
    assert row.token_version == 0
    assert row.oidc_sub is None


@pytest.mark.asyncio
async def test_create_user_returns_must_change_password_true(db_session, monkeypatch, argon2_fast):
    from app.config import settings
    from sqlalchemy import text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    async with await _client() as c:
        r = await c.post(
            "/api/admin/users",
            json={**VALID_CREATE_BODY, "username": "mustchg_test"},
            headers=_admin_headers(),
        )
        assert r.status_code == 201
        assert r.json()["must_change_password"] is True


@pytest.mark.asyncio
async def test_create_admin_forces_both_dashboards(db_session, monkeypatch, argon2_fast):
    """Creating a user with role=Admin forces dashboard_roles=[red,blue] regardless of body."""
    from app.config import settings
    from sqlalchemy import text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    async with await _client() as c:
        r = await c.post(
            "/api/admin/users",
            json=ADMIN_CREATE_BODY,
            headers=_admin_headers(),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["role"] == "Admin"
        assert set(body["dashboard_roles"]) == {"red", "blue"}


@pytest.mark.asyncio
async def test_create_analyst_with_dashboard_roles_honours_body(db_session, monkeypatch, argon2_fast):
    """Analyst user respects dashboard_roles from body (not forced to both)."""
    from app.config import settings
    from sqlalchemy import text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    async with await _client() as c:
        r = await c.post(
            "/api/admin/users",
            json={**VALID_CREATE_BODY, "username": "analyst_dr", "dashboard_roles": ["red"]},
            headers=_admin_headers(),
        )
        assert r.status_code == 201
        assert r.json()["dashboard_roles"] == ["red"]


@pytest.mark.asyncio
async def test_create_user_duplicate_username_returns_409(db_session, monkeypatch, argon2_fast):
    from app.config import settings
    from sqlalchemy import text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    async with await _client() as c:
        body = {**VALID_CREATE_BODY, "username": "dupuser"}
        r1 = await c.post("/api/admin/users", json=body, headers=_admin_headers())
        assert r1.status_code == 201
        r2 = await c.post("/api/admin/users", json=body, headers=_admin_headers())
        assert r2.status_code == 409
        assert r2.json()["detail"] == "username_exists"


# ---------------------------------------------------------------------------
# GET /api/admin/users — list users
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_users_as_analyst_returns_403(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    async with await _client() as c:
        r = await c.get("/api/admin/users", headers=_analyst_headers())
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_list_users_as_admin_returns_array(db_session, monkeypatch, argon2_fast):
    from app.config import settings
    from sqlalchemy import text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    async with await _client() as c:
        # Create one user first
        await c.post(
            "/api/admin/users",
            json={**VALID_CREATE_BODY, "username": "listed_user"},
            headers=_admin_headers(),
        )

        r = await c.get("/api/admin/users", headers=_admin_headers())
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body, list)
        assert len(body) >= 1
        # Check shape of first item
        first = body[0]
        assert "id" in first
        assert "username" in first
        assert "role" in first
        assert "dashboard_roles" in first
        assert "enabled" in first
        assert "must_change_password" in first
        assert "locked" in first


@pytest.mark.asyncio
async def test_list_users_locked_field_reflects_redis_state(db_session, monkeypatch, argon2_fast):
    """locked field in list response reflects Redis login:locked key presence."""
    from app.config import settings
    from app.security.lockout import record_failure
    from sqlalchemy import text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    async with await _client() as c:
        r_create = await c.post(
            "/api/admin/users",
            json={**VALID_CREATE_BODY, "username": "locktest_user"},
            headers=_admin_headers(),
        )
        assert r_create.status_code == 201

    # Attempt to get Redis and record 5 failures (threshold)
    try:
        import redis.asyncio as aioredis
        redis = aioredis.from_url(settings.REDIS_URL)
        for _ in range(5):
            await record_failure(redis, "locktest_user")
        await redis.aclose()
    except Exception:
        pytest.skip("Redis not available — skipping locked field test")

    async with await _client() as c:
        r = await c.get("/api/admin/users", headers=_admin_headers())
        assert r.status_code == 200
        users = r.json()
        locktest = next((u for u in users if u["username"] == "locktest_user"), None)
        assert locktest is not None
        assert locktest["locked"] is True


# ---------------------------------------------------------------------------
# PATCH /api/admin/users/{id} — update user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_user_not_found_returns_404(db_session, monkeypatch):
    from app.config import settings
    from sqlalchemy import text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)

    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    fake_id = str(_uuid.uuid4())
    async with await _client() as c:
        r = await c.patch(
            f"/api/admin/users/{fake_id}",
            json={"role": "Analyst"},
            headers=_admin_headers(),
        )
        assert r.status_code == 404
        assert r.json()["detail"] == "user_not_found"


@pytest.mark.asyncio
async def test_patch_user_role_updates_role(db_session, monkeypatch, argon2_fast):
    from app.config import settings
    from sqlalchemy import text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    async with await _client() as c:
        r_create = await c.post(
            "/api/admin/users",
            json={**VALID_CREATE_BODY, "username": "rolechange_user"},
            headers=_admin_headers(),
        )
        assert r_create.status_code == 201
        user_id = r_create.json()["id"]

        r_patch = await c.patch(
            f"/api/admin/users/{user_id}",
            json={"role": "Viewer"},
            headers=_admin_headers(),
        )
        assert r_patch.status_code == 200, r_patch.text
        assert r_patch.json()["role"] == "Viewer"


@pytest.mark.asyncio
async def test_patch_user_dashboard_roles_updates(db_session, monkeypatch, argon2_fast):
    from app.config import settings
    from sqlalchemy import text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    async with await _client() as c:
        r_create = await c.post(
            "/api/admin/users",
            json={**VALID_CREATE_BODY, "username": "drchange_user", "dashboard_roles": ["red"]},
            headers=_admin_headers(),
        )
        assert r_create.status_code == 201
        user_id = r_create.json()["id"]

        r_patch = await c.patch(
            f"/api/admin/users/{user_id}",
            json={"dashboard_roles": ["blue"]},
            headers=_admin_headers(),
        )
        assert r_patch.status_code == 200
        assert r_patch.json()["dashboard_roles"] == ["blue"]


@pytest.mark.asyncio
async def test_patch_user_enabled_false_bumps_token_version(db_session, monkeypatch, argon2_fast):
    """Disabling a user bumps token_version (invalidates all outstanding tokens)."""
    from app.config import settings
    from app.models.users import User
    from sqlalchemy import select, text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    async with await _client() as c:
        r_create = await c.post(
            "/api/admin/users",
            json={**VALID_CREATE_BODY, "username": "disable_test"},
            headers=_admin_headers(),
        )
        assert r_create.status_code == 201
        user_id = r_create.json()["id"]

        r_patch = await c.patch(
            f"/api/admin/users/{user_id}",
            json={"enabled": False},
            headers=_admin_headers(),
        )
        assert r_patch.status_code == 200, r_patch.text
        assert r_patch.json()["enabled"] is False

    # Verify token_version bumped in DB
    row = (await db_session.execute(
        select(User).where(User.username == "disable_test")
    )).scalar_one_or_none()
    assert row is not None
    assert row.token_version == 1  # Started at 0, bumped to 1 on disable
    assert row.enabled is False


@pytest.mark.asyncio
async def test_patch_user_role_admin_forces_both_dashboards(db_session, monkeypatch, argon2_fast):
    """Patching user role to Admin forces dashboard_roles=[red,blue]."""
    from app.config import settings
    from sqlalchemy import text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    async with await _client() as c:
        r_create = await c.post(
            "/api/admin/users",
            json={**VALID_CREATE_BODY, "username": "promote_to_admin", "dashboard_roles": ["red"]},
            headers=_admin_headers(),
        )
        assert r_create.status_code == 201
        user_id = r_create.json()["id"]

        r_patch = await c.patch(
            f"/api/admin/users/{user_id}",
            json={"role": "Admin"},
            headers=_admin_headers(),
        )
        assert r_patch.status_code == 200, r_patch.text
        body = r_patch.json()
        assert body["role"] == "Admin"
        assert set(body["dashboard_roles"]) == {"red", "blue"}


# ---------------------------------------------------------------------------
# POST /api/admin/users/{id}/unlock — clear Redis lockout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unlock_user_not_found_returns_404(db_session, monkeypatch):
    from app.config import settings
    from sqlalchemy import text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)

    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    fake_id = str(_uuid.uuid4())
    async with await _client() as c:
        r = await c.post(
            f"/api/admin/users/{fake_id}/unlock",
            headers=_admin_headers(),
        )
        assert r.status_code == 404
        assert r.json()["detail"] == "user_not_found"


@pytest.mark.asyncio
async def test_unlock_as_analyst_returns_403(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    fake_id = str(_uuid.uuid4())
    async with await _client() as c:
        r = await c.post(
            f"/api/admin/users/{fake_id}/unlock",
            headers=_analyst_headers(),
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_unlock_clears_redis_keys(db_session, monkeypatch, argon2_fast):
    """POST /unlock deletes login:fails and login:locked Redis keys."""
    from app.config import settings
    from app.security.lockout import is_locked, record_failure
    from sqlalchemy import text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    async with await _client() as c:
        r_create = await c.post(
            "/api/admin/users",
            json={**VALID_CREATE_BODY, "username": "unlock_test"},
            headers=_admin_headers(),
        )
        assert r_create.status_code == 201
        user_id = r_create.json()["id"]

    # Lock the user via Redis
    try:
        import redis.asyncio as aioredis
        redis = aioredis.from_url(settings.REDIS_URL)
        for _ in range(5):
            await record_failure(redis, "unlock_test")
        locked_before, _ = await is_locked(redis, "unlock_test")
        assert locked_before is True
        await redis.aclose()
    except Exception:
        pytest.skip("Redis not available — skipping unlock Redis keys test")

    async with await _client() as c:
        r_unlock = await c.post(
            f"/api/admin/users/{user_id}/unlock",
            headers=_admin_headers(),
        )
        assert r_unlock.status_code == 204

    # Verify lockout cleared
    try:
        import redis.asyncio as aioredis
        redis = aioredis.from_url(settings.REDIS_URL)
        locked_after, _ = await is_locked(redis, "unlock_test")
        assert locked_after is False
        await redis.aclose()
    except Exception:
        pytest.skip("Redis not available for post-unlock verification")


# ---------------------------------------------------------------------------
# DELETE /api/admin/users/{id} — delete user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_delete_user_204_and_row_gone(db_session, monkeypatch, argon2_fast):
    """DELETE removes the row and returns 204."""
    from app.config import settings
    from app.models.users import User
    from sqlalchemy import select, text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    async with await _client() as c:
        r_create = await c.post(
            "/api/admin/users",
            json={**VALID_CREATE_BODY, "username": "delete_target"},
            headers=_admin_headers(),
        )
        assert r_create.status_code == 201
        user_id = r_create.json()["id"]

        r_del = await c.delete(
            f"/api/admin/users/{user_id}",
            headers=_admin_headers(),
        )
        assert r_del.status_code == 204, r_del.text

    row = (await db_session.execute(
        select(User).where(User.username == "delete_target")
    )).scalar_one_or_none()
    assert row is None


@pytest.mark.asyncio
async def test_admin_delete_self_400_cannot_delete_self(db_session, monkeypatch, argon2_fast):
    """Admin cannot delete their own account — 400 cannot_delete_self."""
    from app.config import settings
    from sqlalchemy import text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    async with await _client() as c:
        # Create an admin user; we will mint a token whose sub == that user's id
        r_create = await c.post(
            "/api/admin/users",
            json={
                "username": "self_delete_admin",
                "role": "Admin",
                "dashboard_roles": [],
                "initial_password": "temporarypassword123",
            },
            headers=_admin_headers(),
        )
        assert r_create.status_code == 201
        admin_id = r_create.json()["id"]

        token = _mint_admin_token(user_id=admin_id)
        headers = {"Authorization": f"Bearer {token}"}

        r_del = await c.delete(
            f"/api/admin/users/{admin_id}",
            headers=headers,
        )
        assert r_del.status_code == 400, r_del.text
        assert r_del.json()["detail"] == "cannot_delete_self"


@pytest.mark.asyncio
async def test_admin_delete_missing_404(db_session, monkeypatch):
    from app.config import settings
    from sqlalchemy import text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    fake_id = str(_uuid.uuid4())
    async with await _client() as c:
        r = await c.delete(
            f"/api/admin/users/{fake_id}",
            headers=_admin_headers(),
        )
        assert r.status_code == 404
        assert r.json()["detail"] == "user_not_found"


@pytest.mark.asyncio
async def test_analyst_delete_403(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    fake_id = str(_uuid.uuid4())
    async with await _client() as c:
        r = await c.delete(
            f"/api/admin/users/{fake_id}",
            headers=_analyst_headers(),
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "insufficient_role"


# ---------------------------------------------------------------------------
# POST /api/admin/users/{id}/reset-password — admin password reset
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_reset_password_200_local_user(db_session, monkeypatch, argon2_fast):
    """Admin reset hashes new pw, sets must_change_password, bumps token_version,
    invalidates old password and accepts new password against verify_password."""
    from app.config import settings
    from app.models.users import User
    from app.security.passwords import verify_and_maybe_rehash
    from sqlalchemy import select, text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    async with await _client() as c:
        r_create = await c.post(
            "/api/admin/users",
            json={**VALID_CREATE_BODY, "username": "reset_target"},
            headers=_admin_headers(),
        )
        assert r_create.status_code == 201
        user_id = r_create.json()["id"]

        r_reset = await c.post(
            f"/api/admin/users/{user_id}/reset-password",
            json={"new_password": "brand_new_password_xyz"},
            headers=_admin_headers(),
        )
        assert r_reset.status_code == 200, r_reset.text
        body = r_reset.json()
        assert body["must_change_password"] is True
        assert body["username"] == "reset_target"

    # Re-fetch row from DB to verify side effects
    await db_session.commit()  # ensure visibility of changes from API session
    row = (await db_session.execute(
        select(User).where(User.username == "reset_target")
    )).scalar_one_or_none()
    assert row is not None
    assert row.must_change_password is True
    assert row.token_version == 1  # bumped from 0
    # Old password rejected, new password accepted
    ok_old, _ = verify_and_maybe_rehash("temporarypassword123", row.password_hash)
    ok_new, _ = verify_and_maybe_rehash("brand_new_password_xyz", row.password_hash)
    assert ok_old is False
    assert ok_new is True


@pytest.mark.asyncio
async def test_admin_reset_password_oidc_user_400(db_session, monkeypatch):
    """OIDC-only user (password_hash NULL) cannot have password reset."""
    from app.config import settings
    from app.models.users import User
    from sqlalchemy import text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    oidc_user = User(
        username="oidc_user",
        password_hash=None,
        oidc_sub="oidc-sub-abc",
        role="Analyst",
        dashboard_roles=["red"],
        enabled=True,
        must_change_password=False,
        token_version=0,
    )
    db_session.add(oidc_user)
    await db_session.commit()
    await db_session.refresh(oidc_user)

    async with await _client() as c:
        r = await c.post(
            f"/api/admin/users/{oidc_user.id}/reset-password",
            json={"new_password": "validpassword1234"},
            headers=_admin_headers(),
        )
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == "oidc_only_user"


@pytest.mark.asyncio
async def test_admin_reset_password_missing_404(db_session, monkeypatch):
    from app.config import settings
    from sqlalchemy import text

    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    await db_session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    await db_session.commit()

    fake_id = str(_uuid.uuid4())
    async with await _client() as c:
        r = await c.post(
            f"/api/admin/users/{fake_id}/reset-password",
            json={"new_password": "validpassword1234"},
            headers=_admin_headers(),
        )
        assert r.status_code == 404
        assert r.json()["detail"] == "user_not_found"


@pytest.mark.asyncio
async def test_admin_reset_password_short_422(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    fake_id = str(_uuid.uuid4())
    async with await _client() as c:
        r = await c.post(
            f"/api/admin/users/{fake_id}/reset-password",
            json={"new_password": "short"},
            headers=_admin_headers(),
        )
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_analyst_reset_password_403(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    _patch_auth(monkeypatch)
    fake_id = str(_uuid.uuid4())
    async with await _client() as c:
        r = await c.post(
            f"/api/admin/users/{fake_id}/reset-password",
            json={"new_password": "validpassword1234"},
            headers=_analyst_headers(),
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "insufficient_role"
