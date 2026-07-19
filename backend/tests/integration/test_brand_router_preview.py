"""Integration tests for the brand router - preview endpoint + Redis caching (12-06)."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.integration


def _make_auth_user(role: str = "Admin", project_id: uuid.UUID | None = None, project_rank: int = 3):
    from app.security.jwt import AuthUser

    pm: dict[str, int] = {}
    if project_id is not None:
        pm[str(project_id)] = project_rank

    return AuthUser(
        id=str(uuid.uuid4()),
        role=role,
        dashboard_roles=["red", "blue"],
        jti=str(uuid.uuid4()),
        token_version=0,
        project_memberships=pm,
        pm_truncated=False,
    )


@pytest_asyncio.fixture
async def brand_app(db_engine, _migrations_applied):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from fastapi import FastAPI

    from app.database import get_session
    from app.middleware.auth import require_auth
    from app.routers.brand import router as brand_router

    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    app = FastAPI()
    app.include_router(brand_router, prefix="/api")

    async def override_session():
        async with factory() as session:
            yield session

    admin_user = _make_auth_user(role="Admin")
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_auth] = lambda: admin_user
    yield app, factory, admin_user


async def _seed_project(db_session, admin_user_id: str) -> uuid.UUID:
    pid = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO projects (id, name, engagement_type, created_by, archived)
            VALUES (CAST(:id AS uuid), :name, 'red_team', :created_by, false)
            """
        ),
        {"id": str(pid), "name": f"brand-proj-{pid}", "created_by": admin_user_id},
    )
    await db_session.commit()
    return pid


class _FakeRedis:
    """Minimal async Redis stand-in - counts get/setex calls for cache-behaviour asserts."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.gets = 0
        self.setexes = 0

    async def get(self, key: str):
        self.gets += 1
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.setexes += 1
        self.store[key] = value


@pytest.mark.asyncio
async def test_preview_endpoint_returns_response_shape(brand_app, db_session, monkeypatch):
    app, _factory, admin_user = brand_app
    pid = await _seed_project(db_session, admin_user.id)

    fake = _FakeRedis()

    async def _fake_get_redis():
        return fake

    import app.routers.brand as brand_mod
    monkeypatch.setattr(brand_mod, "get_redis", _fake_get_redis)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            f"/api/projects/{pid}/brand/preview?term=neverseenbefore&term_type=keyword"
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "preview_matches" in body
    assert "percent" in body
    assert "warning" in body


@pytest.mark.asyncio
async def test_preview_endpoint_uses_cache_on_second_call(brand_app, db_session, monkeypatch):
    app, _factory, admin_user = brand_app
    pid = await _seed_project(db_session, admin_user.id)

    fake = _FakeRedis()

    async def _fake_get_redis():
        return fake

    import app.routers.brand as brand_mod
    monkeypatch.setattr(brand_mod, "get_redis", _fake_get_redis)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.get(
            f"/api/projects/{pid}/brand/preview?term=cachetest&term_type=keyword"
        )
        assert r1.status_code == 200
        # first call populated the cache
        assert fake.setexes == 1

        r2 = await client.get(
            f"/api/projects/{pid}/brand/preview?term=cachetest&term_type=keyword"
        )
        assert r2.status_code == 200
        # second call should hit cache - no new SETEX
        assert fake.setexes == 1
        assert r1.json() == r2.json()


@pytest.mark.asyncio
async def test_preview_endpoint_rejects_bad_term_type(brand_app, db_session, monkeypatch):
    app, _factory, admin_user = brand_app
    pid = await _seed_project(db_session, admin_user.id)

    fake = _FakeRedis()

    async def _fake_get_redis():
        return fake

    import app.routers.brand as brand_mod
    monkeypatch.setattr(brand_mod, "get_redis", _fake_get_redis)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            f"/api/projects/{pid}/brand/preview?term=x&term_type=bogus"
        )
    # FastAPI validates Literal query params → 422
    assert r.status_code == 422
