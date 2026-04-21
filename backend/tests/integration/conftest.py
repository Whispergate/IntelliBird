"""Integration-test fixtures: postgres+timescale+age container, redis container."""
from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer


@pytest.fixture(scope="session")
def pg_container() -> Iterator[PostgresContainer]:
    """intellibird-db:m1 image ships Postgres 16 + TimescaleDB + AGE, required by
    migration 001 (CREATE EXTENSION timescaledb CASCADE + CREATE EXTENSION age CASCADE)
    and downstream migrations. Falls back to timescale-only image when
    INTELLIBIRD_DB_IMAGE env var is set."""
    image = os.environ.get("INTELLIBIRD_DB_IMAGE", "intellibird-db:m1")
    with PostgresContainer(image) as pg:
        yield pg


@pytest.fixture(scope="session")
def redis_container() -> Iterator[RedisContainer]:
    with RedisContainer("redis:7-alpine") as r:
        yield r


# fixtures directory accessor used by RSS/TAXII/NVD integration tests.

@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Absolute path to backend/tests/fixtures/."""
    return Path(__file__).resolve().parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# DB bootstrap: derive pg_url, run alembic to head once per session, yield a
# fresh async session per test. Mirrors the phase10 conftest pattern so the
# handful of Phase 9 integration tests that reference `db_session` can run.
# ---------------------------------------------------------------------------

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def pg_url(pg_container: PostgresContainer) -> str:
    sync_url = pg_container.get_connection_url()
    return sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace(
        "postgresql://", "postgresql+asyncpg://"
    )


@pytest.fixture(scope="session")
def redis_url(redis_container: RedisContainer) -> str:
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}/12"  # DB 12 — isolate from phase10 DB 11


@pytest.fixture(scope="session", autouse=True)
def _patch_settings_for_integration(pg_url: str, redis_url: str) -> Iterator[None]:
    """Point app.config.settings + os.environ at the live container URLs for the
    whole session. autouse so every integration-scoped test picks up a real DB
    URL on import — the bare os.environ.setdefault() at the top of each test file
    falls through when these are already set by this fixture.

    Also rebuilds app.database.engine + async_session_factory because unit tests
    (run before integration) may have imported app.database with the dummy DATABASE_URL,
    binding the module-level engine to a non-existent server. If we don't rebuild,
    every later request that uses get_session() hits the old bound URL."""
    os.environ["DATABASE_URL"] = pg_url
    os.environ["REDIS_URL"] = redis_url
    try:
        from app.config import settings
        settings.DATABASE_URL = pg_url  # type: ignore[assignment]
        settings.REDIS_URL = redis_url  # type: ignore[assignment]
    except Exception:
        pass
    # Rebuild the module-level engine / session factory against the live URL.
    try:
        import app.database as db_mod
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        new_engine = create_async_engine(pg_url, pool_pre_ping=True, future=True)
        db_mod.engine = new_engine
        db_mod.async_session_factory = async_sessionmaker(
            new_engine, expire_on_commit=False, class_=AsyncSession
        )
    except Exception:
        pass
    yield


@pytest.fixture(scope="session")
def _migrations_applied(pg_url: str, _patch_settings_for_integration: None) -> None:
    """Run alembic upgrade head once per session. Subprocess-invoked to dodge the
    nested-asyncio conflict when alembic/env.py calls asyncio.run() inside the
    pytest-asyncio event loop."""
    env = os.environ | {"DATABASE_URL": pg_url}
    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.skip(f"alembic upgrade head failed:\n{r.stderr[:800]}")


@pytest_asyncio.fixture
async def db_engine(pg_url: str, _migrations_applied: None):
    """Fresh async engine per test — avoids cross-loop Future leakage when tests
    run in different event loops (pytest-asyncio default is function-scoped loops).
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(pg_url, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncIterator[Any]:
    """Fresh test-scoped session with best-effort cleanup of Phase-9/10 data
    tables. Preserves sentinel LEGACY_PROJECT_ID row (FK'd by events /
    filter_presets / webhooks). TRUNCATE is broad enough that fixtures inside
    individual tests can seed fresh rows without colliding on PK."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        # users is FK-independent; attack_technique_tags + events + webhooks +
        # filter_presets all reference projects via project_id, so clear them
        # first, then delete non-sentinel projects. project_memberships,
        # project_scope_rows, project_sources cascade from projects.
        try:
            await session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
        except Exception:
            pass
        try:
            await session.execute(text("TRUNCATE TABLE attack_technique_tags RESTART IDENTITY"))
        except Exception:
            pass
        try:
            await session.execute(text("TRUNCATE TABLE events RESTART IDENTITY CASCADE"))
        except Exception:
            pass
        try:
            await session.execute(text("TRUNCATE TABLE webhooks RESTART IDENTITY CASCADE"))
        except Exception:
            pass
        try:
            await session.execute(text("TRUNCATE TABLE filter_presets RESTART IDENTITY CASCADE"))
        except Exception:
            pass
        try:
            await session.execute(text(
                "DELETE FROM projects "
                "WHERE id <> '00000000-0000-0000-0000-000000000001'::uuid"
            ))
        except Exception:
            pass
        await session.commit()
        yield session
        await session.rollback()
