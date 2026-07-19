"""Integration tests for admin/sources CRUD router -.

Uses testcontainers Postgres (intellibird-db:m1 image) + alembic upgrade head
to prove the full HTTP round-trip against a live Postgres database.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def live_db_sources():
    """Module-scoped live PG container with alembic schema applied."""
    with PostgresContainer("intellibird-db:m1") as pg:
        url = pg.get_connection_url()
        parsed_url = make_url(url)
        asyncpg_url = (
            f"postgresql+asyncpg://{parsed_url.username}:{parsed_url.password}"
            f"@{parsed_url.host}:{parsed_url.port}/{parsed_url.database}"
        )
        env = os.environ | {
            "DATABASE_URL": asyncpg_url,
            "SECRET_KEY": "x" * 48,
            "JWT_SIGNING_KEY": "j" * 64,
            "REDIS_URL": "redis://localhost:1",  # unreachable - pub/sub fire-and-forget
        }
        r = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"alembic upgrade failed: {r.stderr[:500]}")
        yield asyncpg_url, env


@pytest_asyncio.fixture
async def sources_client(live_db_sources):
    asyncpg_url, env = live_db_sources

    # Patch settings to point at the test DB. Env must be set BEFORE the first
    # import of app.config so module-level `settings = Settings()` sees the
    # required SECRET_KEY + JWT_SIGNING_KEY (respectively).
    for k, v in env.items():
        os.environ[k] = v
    import importlib
    import app.config as cfg_module
    importlib.reload(cfg_module)

    engine = create_async_engine(asyncpg_url, pool_pre_ping=True, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    from app.database import get_session
    from app.middleware.auth import require_admin, require_analyst_or_above, require_auth
    from app.routers.admin.sources import router
    from app.security.jwt import AuthUser

    app = FastAPI()
    app.include_router(router)

    async def override_session():
        async with factory() as session:
            yield session

    def _fake_admin() -> AuthUser:
        # AUTH-02 guards admin routes. Bypass the middleware chain
        # (not mounted on this minimal test app) by overriding the dependency
        # so the CRUD test exercises the business logic, not auth plumbing.
        return AuthUser(
            id="00000000-0000-0000-0000-000000000099",
            role="Admin",
            dashboard_roles=["red", "blue"],
            jti="test-jti",
            token_version=0,
            project_memberships={},
            pm_truncated=False,
        )

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_admin] = _fake_admin
    app.dependency_overrides[require_analyst_or_above] = _fake_admin
    app.dependency_overrides[require_auth] = _fake_admin

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    await engine.dispose()


@pytest.mark.asyncio
async def test_sources_full_crud_roundtrip(sources_client):
    """POST create → GET list → GET /{id} → PATCH → GET /{id} reflect update
 → GET /{id}/event-count → DELETE → GET /{id} 404."""
    payload = {
        "name": "Integration RSS Feed",
        "feed_type": "rss",
        "url": "https://example.com/rss.xml",
        "poll_interval_sec": 3600,
        "hot_retention_days": 30,
        "archive_policy": "drop",
        "enabled": True,
    }

    # POST - create
    create_resp = await sources_client.post("/admin/sources", json=payload)
    assert create_resp.status_code == 201
    src = create_resp.json()
    src_id = src["id"]
    assert src["name"] == "Integration RSS Feed"
    assert src["feed_type"] == "rss"
    assert src["enabled"] is True
    assert "credentials_enc" not in create_resp.text

    # GET list - contains the created source
    list_resp = await sources_client.get("/admin/sources")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert any(item["id"] == src_id for item in items)
    assert "credentials_enc" not in list_resp.text

    # GET /{id} - returns the same source
    get_resp = await sources_client.get(f"/admin/sources/{src_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == src_id
    assert "credentials_enc" not in get_resp.text

    # PATCH - update enabled=False
    patch_resp = await sources_client.patch(
        f"/admin/sources/{src_id}", json={"enabled": False}
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["enabled"] is False

    # GET /{id} - reflects the update
    get_after_patch = await sources_client.get(f"/admin/sources/{src_id}")
    assert get_after_patch.status_code == 200
    assert get_after_patch.json()["enabled"] is False

    # GET /{id}/event-count - zero events
    count_resp = await sources_client.get(f"/admin/sources/{src_id}/event-count")
    assert count_resp.status_code == 200
    assert count_resp.json()["count"] == 0

    # DELETE
    del_resp = await sources_client.delete(f"/admin/sources/{src_id}")
    assert del_resp.status_code == 204

    # GET /{id} - 404
    not_found = await sources_client.get(f"/admin/sources/{src_id}")
    assert not_found.status_code == 404
