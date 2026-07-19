"""Shared fixtures for project scoping tests.

Wave 1 plan 10-02 activates:
  - monkeypatch_module (session-scoped monkeypatch shim)
  - pg_container (session-scoped testcontainers Postgres)
  - redis_container (session-scoped testcontainers Redis)
  - db_engine (module-scoped - runs alembic head migrations)
  - db_session (test-scoped async SQLAlchemy session)
  - two_projects (real body - seeds two projects with shared-compare artefacts)
  - users_matrix (real body - seeds 5 users + builds pm-empty tokens)
  - memberships_60 (real body - seeds 60 rows + issues token via build_membership_claim)

Gracefully skips when testcontainers are unavailable (no Docker) so CI without
the container runtime stays green.
"""
from __future__ import annotations

import os
import uuid as _uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Env defaults - required for app.config.Settings() at import time
# ---------------------------------------------------------------------------
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


# ---------------------------------------------------------------------------
# Session-scoped monkeypatch (pytest's monkeypatch is function-scoped)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def monkeypatch_module() -> Iterator[pytest.MonkeyPatch]:
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


# ---------------------------------------------------------------------------
# Testcontainers: Postgres + Redis
# ---------------------------------------------------------------------------

def _testcontainers_available() -> bool:
    try:
        import testcontainers.postgres  # noqa: F401
        import testcontainers.redis  # noqa: F401
    except ImportError:
        return False
    return os.environ.get("SKIP_TESTCONTAINERS") != "1"


@pytest.fixture(scope="session")
def pg_container():
    if not _testcontainers_available():
        pytest.skip("testcontainers unavailable - install or unset SKIP_TESTCONTAINERS")
    from testcontainers.postgres import PostgresContainer
    # intellibird-db:m1 ships TimescaleDB + AGE; required for migration 001.
    with PostgresContainer("intellibird-db:m1") as pg:
        yield pg


@pytest.fixture(scope="session")
def redis_container():
    if not _testcontainers_available():
        pytest.skip("testcontainers unavailable - install or unset SKIP_TESTCONTAINERS")
    from testcontainers.redis import RedisContainer
    with RedisContainer("redis:7-alpine") as r:
        yield r


# ---------------------------------------------------------------------------
# DB bootstrap: run alembic to head + yield a fresh session per test
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pg_url(pg_container) -> str:
    sync_url = pg_container.get_connection_url()
    return sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace(
        "postgresql://", "postgresql+asyncpg://"
    )


@pytest.fixture(scope="module")
def redis_url(redis_container) -> str:
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}/11"  # DB 11 - isolate from other test suites


@pytest.fixture(scope="module", autouse=True)
def _patch_settings(pg_url, redis_url, monkeypatch_module) -> None:
    os.environ["DATABASE_URL"] = pg_url
    os.environ["REDIS_URL"] = redis_url
    from app.config import settings
    monkeypatch_module.setattr(settings, "DATABASE_URL", pg_url, raising=False)
    monkeypatch_module.setattr(settings, "REDIS_URL", redis_url, raising=False)
    monkeypatch_module.setattr(settings, "AUTH_ENABLED", False, raising=False)


@pytest.fixture(scope="module")
def _migrations_applied(pg_url) -> None:
    """Run alembic upgrade head via subprocess exactly once per module.

    Subprocess invocation avoids the nested asyncio.run() conflict triggered when
    alembic/env.py calls asyncio.run(run_async_migrations()) from inside the
    pytest-asyncio event loop. Matches test_009_compressed_chunk.py pattern.
    """
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


@pytest_asyncio.fixture
async def db_engine(pg_url, _migrations_applied):
    """Fresh async engine per test - avoids cross-loop Future leakage when tests
    run in different event loops (pytest-asyncio default is function-scoped loops).
    Migrations run once per module via `_migrations_applied`.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(pg_url, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncIterator[Any]:
    """Fresh test-scoped session.

    TRUNCATEs the test tables (users, projects + cascades to memberships,
    scope_rows, sources) before yielding so each test starts clean - fixtures
    commit real rows, and a rolling tx rollback at teardown does not undo them.
    Preserves sentinel LEGACY_PROJECT_ID row (required by FK back-reference from
    events/filter_presets/webhooks).
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        # TRUNCATE users first (FK-independent), then clear everything that
        # references projects (events, filter_presets, webhooks,
        # attack_technique_tags) so the subsequent DELETE FROM projects
        # doesn't hit ON DELETE RESTRICT foreign keys. project_memberships,
        # project_scope_rows, project_sources all have ON DELETE CASCADE
        # from projects so DELETE FROM projects handles them implicitly.
        await session.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
        await session.execute(text(
            "TRUNCATE TABLE attack_technique_tags RESTART IDENTITY"
        ))
        # events is a hypertable - TRUNCATE works fine
        await session.execute(text("TRUNCATE TABLE events RESTART IDENTITY CASCADE"))
        await session.execute(text(
            "TRUNCATE TABLE webhooks RESTART IDENTITY CASCADE"
        ))
        await session.execute(text(
            "TRUNCATE TABLE filter_presets RESTART IDENTITY CASCADE"
        ))
        await session.execute(text(
            "DELETE FROM projects "
            "WHERE id <> '00000000-0000-0000-0000-000000000001'::uuid"
        ))
        await session.commit()
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Legacy project id literal (ORM-level constant - no DB round trip needed)
# ---------------------------------------------------------------------------

@pytest.fixture
def legacy_project_id() -> str:
    """Sentinel UUID constant; matches app.models.projects.LEGACY_PROJECT_ID."""
    return "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Wave 1 fixtures (real bodies - plan 10-02 activates)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def two_projects(db_session) -> dict[str, Any]:
    """Seed two projects with disjoint scope rows for PRJ-06 compare + PRJ-05 membership tests.

    Returned dict:
      project_a, project_b: Project ORM rows
      shared_actor_name, shared_technique_id, shared_ioc: strings used in compare tests
    """
    from app.models.projects import Project
    a = Project(
        id=_uuid.uuid4(), name="Project A", engagement_type="red_team",
        description="Compare test A", created_by="system", archived=False,
    )
    b = Project(
        id=_uuid.uuid4(), name="Project B", engagement_type="tiber",
        description="Compare test B", created_by="system", archived=False,
    )
    db_session.add_all([a, b])
    await db_session.commit()
    await db_session.refresh(a)
    await db_session.refresh(b)
    return {
        "project_a": a,
        "project_b": b,
        "shared_actor_name": "apt28",
        "shared_technique_id": "T1566",
        "shared_ioc": "malicious.example.com",
    }


@pytest_asyncio.fixture
async def users_matrix(db_session, jwt_settings, argon2_fast) -> dict[str, Any]:
    """Seed five users covering every authority-matrix cell + mint pm-empty tokens.

    Dependencies:
      - `argon2_fast` (tests/conftest.py): swaps pwdlib singleton for ~5ms/hash Argon2
        params (production ~200ms/hash). 5 users × production cost would add ~1s
        per test; with argon2_fast this fixture completes in ~25ms.
      - `jwt_settings` (tests/conftest.py): sets JWT_SIGNING_KEY; also returns the key.

    Python-side UUID generation (`id=_uuid.uuid4()`) + explicit `token_version=0`
    are REQUIRED per CONTEXT.md §Established Patterns: SQLite-friendly and downstream
    tests reference token_version in mint calls.

    Returned dict:
      global_admin, global_analyst, project_lead_user, project_contributor_user,
      project_observer_user: User ORM rows
      tokens: dict[role_label, access_token_str]
    """
    from app.models.users import User
    from app.security.jwt import mint_access_token_with_pm
    from app.security.passwords import hash_password  # patched by argon2_fast

    admin = User(
        id=_uuid.uuid4(), username="admin_u",
        password_hash=hash_password("x"), role="Admin",
        dashboard_roles=["red", "blue"], token_version=0,
    )
    analyst = User(
        id=_uuid.uuid4(), username="analyst_u",
        password_hash=hash_password("x"), role="Analyst",
        dashboard_roles=["red"], token_version=0,
    )
    lead = User(
        id=_uuid.uuid4(), username="lead_u",
        password_hash=hash_password("x"), role="Analyst",
        dashboard_roles=["blue"], token_version=0,
    )
    contrib = User(
        id=_uuid.uuid4(), username="contrib_u",
        password_hash=hash_password("x"), role="Analyst",
        dashboard_roles=["blue"], token_version=0,
    )
    observer = User(
        id=_uuid.uuid4(), username="observer_u",
        password_hash=hash_password("x"), role="Viewer",
        dashboard_roles=["blue"], token_version=0,
    )
    for u in (admin, analyst, lead, contrib, observer):
        db_session.add(u)
    await db_session.commit()
    for u in (admin, analyst, lead, contrib, observer):
        await db_session.refresh(u)

    def _tok(u: Any) -> str:
        tok, _ = mint_access_token_with_pm(
            str(u.id), u.role, u.dashboard_roles, u.token_version,
            jwt_settings, [], False,
        )
        return tok

    return {
        "global_admin": admin,
        "global_analyst": analyst,
        "project_lead_user": lead,
        "project_contributor_user": contrib,
        "project_observer_user": observer,
        "tokens": {
            "admin": _tok(admin),
            "analyst": _tok(analyst),
            "lead": _tok(lead),
            "contributor": _tok(contrib),
            "observer": _tok(observer),
        },
    }


@pytest_asyncio.fixture
async def memberships_60(db_session, users_matrix, jwt_settings) -> dict[str, Any]:
    """Seed 60 project_memberships rows for global_analyst and issue a real token
    via build_membership_claim - exercises the >PM_CUTOFF truncation branch.
    """
    from app.models.projects import Project, ProjectMembership
    from app.security.jwt import build_membership_claim, mint_access_token_with_pm

    user = users_matrix["global_analyst"]
    for i in range(60):
        p = Project(
            id=_uuid.uuid4(), name=f"Proj{i}",
            engagement_type="internal", created_by="system", archived=False,
        )
        db_session.add(p)
        await db_session.flush()
        db_session.add(ProjectMembership(
            user_sub=str(user.id), project_id=p.id,
            project_role="Contributor", added_by="system",
        ))
    await db_session.commit()
    pm, truncated = await build_membership_claim(db_session, [str(user.id)])
    tok, _ = mint_access_token_with_pm(
        str(user.id), user.role, user.dashboard_roles, user.token_version,
        jwt_settings, pm, truncated,
    )
    return {"token": tok, "pm": pm, "truncated": truncated, "user": user}


@pytest.fixture
async def testcontainer_compressed_chunk(db_session) -> None:
    """Kept as an owning-plan-10-01 stub - migration 009 compressed-chunk spike."""
    pytest.skip("Wave 0 stub - plan 10-01 owns testcontainer_compressed_chunk")
