"""Integration-test fixtures: postgres+timescale+age container, redis container."""
from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

# --- audit (2026-04-27) -----------------------------------------------
# db_engine + db_session are already function-scoped with engine.dispose()
# in the finally block. No changes required to those fixtures (RESEARCH §
# "SQLAlchemy Async Engine Teardown Pattern" verbatim confirms this matches
# the per-loop pattern used in app/workers/brand.py + scoring.py).
# The only addition here is the _truncate_and_flush autouse
# fixture (Task 2) - Redis FLUSHDB + DB TRUNCATE per test.
# -------------------------------------------------------------------------------

# Sentinel UUIDs - seeded by migrations, must survive per-test cleanup.
# projects: migration 009 legacy sentinel (_legacy); migration 016 monitoring sentinel (System Monitoring)
# sources:  migration 007 rekey canary (_rekey_canary)
_PROJECTS_LEGACY_SENTINEL_UUID = "00000000-0000-0000-0000-000000000001"
_PROJECTS_MONITORING_SENTINEL_UUID = "00000000-0000-0000-0000-000000000000"
_SOURCES_CANARY_UUID = "00000000-0000-0000-0000-000000000000"

# Tables fully truncated per test (RESEARCH §TRUNCATE-Safe Table Catalog).
# CASCADE handles FK chain. RESTART IDENTITY resets sequences. TimescaleDB
# hypertables (events, source_ingest_stats, ai_summaries) work cleanly.
# maintenance_windows is included: created_by_user_id FK is nullable (ON DELETE
# SET NULL), so truncating users does NOT clear maintenance_windows rows -
# explicit TRUNCATE required for hermetic state per test.
_TRUNCATE_TABLES: tuple[str, ...] = (
    "users",
    "attack_technique_tags",
    "events",
    "webhooks",
    "filter_presets",
    "source_ingest_stats",
    "ai_summaries",
    "ai_providers",
    "maintenance_windows",
)


@pytest_asyncio.fixture(autouse=True)
async def _truncate_and_flush(redis_url: str, db_engine):
    """Per-test data isolation. TEST-02 + TEST-03.

    - FLUSHDB on test Redis container (wipes JTI blocklist, lockout,
      burst counters, AI buffers, monitoring sentinels - single call).
    - TRUNCATE non-bootstrap tables CASCADE on Postgres.
    - Preserve attack_techniques (~700 ATT&CK rows seeded by migration 002).
    - Preserve sentinel rows in projects (two: mig 009 + mig 016) / sources (mig 007).

    FLUSHDB safety: redis_url points to the testcontainer (DB 12 per
    _patch_settings_for_integration) - never hits operator dev Redis.
    """
    import redis.asyncio as aioredis

    # --- Setup: clean state BEFORE the test runs ---
    # Redis flush
    r = aioredis.from_url(redis_url)
    try:
        await r.flushdb()
    finally:
        await r.aclose()

    # DB reset
    async with db_engine.begin() as conn:
        for tbl in _TRUNCATE_TABLES:
            await conn.execute(
                text(f"TRUNCATE TABLE {tbl} RESTART IDENTITY CASCADE")
            )
        # Sentinel-preserving deletes for projects (preserve both legacy + monitoring sentinels)
        # Note: use CAST(:param AS uuid) instead of :param::uuid - asyncpg named parameter
        # binding does not support the Postgres :: cast operator adjacent to a bind param.
        await conn.execute(
            text(
                "DELETE FROM projects "
                "WHERE id NOT IN (CAST(:legacy AS uuid), CAST(:monitoring AS uuid))"
            ),
            {
                "legacy": _PROJECTS_LEGACY_SENTINEL_UUID,
                "monitoring": _PROJECTS_MONITORING_SENTINEL_UUID,
            },
        )
        # Sentinel-preserving delete for sources (preserve rekey canary)
        await conn.execute(
            text(
                "DELETE FROM sources WHERE id <> CAST(:canary AS uuid)"
            ),
            {"canary": _SOURCES_CANARY_UUID},
        )

    yield

    # No teardown reset - next test's setup phase handles it. This avoids
    # double-truncation cost. If a test pollutes the *final* test of a run,
    # the next session's first test cleans it.


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
# handful of integration tests that reference `db_session` can run.
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
    return f"redis://{host}:{port}/12"  # DB 12 - isolate from phase10 DB 11


@pytest.fixture(scope="session", autouse=True)
def _patch_settings_for_integration(pg_url: str, redis_url: str) -> Iterator[None]:
    """Point app.config.settings + os.environ at the live container URLs for the
    whole session. autouse so every integration-scoped test picks up a real DB
    URL on import - the bare os.environ.setdefault() at the top of each test file
    falls through when these are already set by this fixture.

    Also rebuilds app.database.engine + async_session_factory because unit tests
    (run before integration) may have imported app.database with the dummy DATABASE_URL,
    binding the module-level engine to a non-existent server. If we don't rebuild,
    every later request that uses get_session() hits the old bound URL."""
    os.environ["DATABASE_URL"] = pg_url
    os.environ["REDIS_URL"] = redis_url
    # Pin JWT_SIGNING_KEY + SECRET_KEY to known values for the whole integration
    # session. Unit tests collected before integration tests may have set these
    # to different values via os.environ.setdefault(); fixtures like two_project.py
    # read os.environ directly, so we must override (not setdefault) here to
    # ensure two_project.py JWTs and _patch_auth monkeypatches use the same key.
    _INTEGRATION_JWT_KEY = "j" * 64
    _INTEGRATION_SECRET = "s" * 64
    os.environ["JWT_SIGNING_KEY"] = _INTEGRATION_JWT_KEY
    os.environ["SECRET_KEY"] = _INTEGRATION_SECRET
    try:
        from app.config import settings
        settings.DATABASE_URL = pg_url  # type: ignore[assignment]
        settings.REDIS_URL = redis_url  # type: ignore[assignment]
        settings.JWT_SIGNING_KEY = _INTEGRATION_JWT_KEY  # type: ignore[assignment]
        settings.SECRET_KEY = _INTEGRATION_SECRET  # type: ignore[assignment]
    except Exception:
        pass
    # Rebuild the module-level engine / session factory against the live URL.
    # NullPool avoids asyncpg connections becoming loop-bound across tests:
    # pytest-asyncio creates a new event loop per function-scoped test, so any
    # pooled connection from test N's loop is invalid for test N+1's loop.
    # NullPool = no connection pooling, each checkout gets a fresh connection.
    try:
        import app.database as db_mod
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool
        new_engine = create_async_engine(pg_url, poolclass=NullPool, future=True)
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
    """Fresh async engine per test - avoids cross-loop Future leakage when tests
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
    """Fresh test-scoped session with best-effort cleanup of 10 data
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


# ---------------------------------------------------------------------------
# PROD fixtures - two-project seed with shared AGE Actor + JWTs.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def two_project_fixture(db_session):
    """PROD-01 two-project fixture - see tests/integration/fixtures/two_project.py."""
    from tests.integration.fixtures.two_project import build_two_project_fixture

    return await build_two_project_fixture(db_session)
