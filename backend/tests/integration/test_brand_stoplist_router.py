"""Integration tests for brand stoplist CRUD routes — Phase 21 / BRAND-01.

Tests the per-project brand stoplist: GET (Observer+), POST (Lead+), DELETE (Lead+).

Auth fixture pattern mirrors test_brand_router_terms.py (_make_auth_user + stoplist_app).
Phase 19 hermetic fixtures (_truncate_and_flush autouse) provide DB isolation.

NOTE: brand_stoplist_terms.created_by_user_id is an FK to users.id. Tests that
call POST routes must seed the auth user's UUID in the users table to avoid FK
violation (which would otherwise surface as a 409 IntegrityError, not a 201).
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.integration

# Observer = rank 1, Contributor = rank 2, Lead = rank 3
_OBSERVER_RANK = 1
_CONTRIBUTOR_RANK = 2
_LEAD_RANK = 3


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _make_auth_user(
    role: str = "Analyst",
    project_id: uuid.UUID | None = None,
    project_rank: int = _LEAD_RANK,
    user_id: str | None = None,
):
    """Build a minimal AuthUser stub. If user_id is provided, reuse it."""
    from app.security.jwt import AuthUser

    uid = user_id or str(uuid.uuid4())
    pm: dict[str, int] = {}
    if project_id is not None:
        pm[str(project_id)] = project_rank

    return AuthUser(
        id=uid,
        role=role,
        dashboard_roles=["red", "blue"],
        jti=str(uuid.uuid4()),
        token_version=0,
        project_memberships=pm,
        pm_truncated=False,
    )


# ---------------------------------------------------------------------------
# App fixture — minimal FastAPI with brand router + session override
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def stoplist_app(db_engine, _migrations_applied):
    """Minimal FastAPI app with brand router wired to test DB engine."""
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

    app.dependency_overrides[get_session] = override_session

    yield app, factory


async def _seed_user(factory, user_id: str) -> None:
    """Insert a user row so created_by_user_id FK is satisfied.

    brand_stoplist_terms.created_by_user_id FK → users.id requires the auth
    user's UUID to exist in users when the POST route commits.
    """
    async with factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO users (id, username, role, token_version)
                VALUES (CAST(:id AS uuid), :username, 'Analyst', 0)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": user_id, "username": f"testuser-{user_id[:8]}"},
        )
        await session.commit()


async def _seed_project(factory, user_id: str) -> uuid.UUID:
    """Insert a user + project row; return the project's UUID."""
    await _seed_user(factory, user_id)
    pid = uuid.uuid4()
    async with factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO projects (id, name, engagement_type, created_by, archived)
                VALUES (CAST(:id AS uuid), :name, 'red_team', :created_by, false)
                """
            ),
            {"id": str(pid), "name": f"stoplist-proj-{pid}", "created_by": user_id},
        )
        await session.commit()
    return pid


def _patch_auth(app, user):
    """Override require_auth to return a fixed AuthUser."""
    from app.middleware.auth import require_auth

    def _override():
        return user

    app.dependency_overrides[require_auth] = _override


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_stoplist_returns_empty_for_fresh_project(stoplist_app):
    """GET /stoplist as Observer returns [] for a project with no stoplist terms."""
    app, factory = stoplist_app
    lead_id = str(uuid.uuid4())
    pid = await _seed_project(factory, lead_id)
    # Observer rank on this project — Observer can read, cannot write
    observer = _make_auth_user(role="Analyst", project_id=pid, project_rank=_OBSERVER_RANK, user_id=lead_id)
    _patch_auth(app, observer)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/api/projects/{pid}/brand/stoplist")

    assert r.status_code == 200, r.text
    assert r.json() == []


@pytest.mark.asyncio
async def test_add_term_lead_returns_201(stoplist_app):
    """POST as Lead → 201; body contains id, term, created_at; GET confirms it."""
    app, factory = stoplist_app
    lead_id = str(uuid.uuid4())
    pid = await _seed_project(factory, lead_id)
    # Lead auth — same user_id as seeded in DB so FK is satisfied
    lead = _make_auth_user(role="Analyst", project_id=pid, project_rank=_LEAD_RANK, user_id=lead_id)
    _patch_auth(app, lead)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{pid}/brand/stoplist",
            json={"term": "noise.example"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert "id" in body
        assert body["term"] == "noise.example"
        assert "created_at" in body

        # GET confirms it's present
        r2 = await client.get(f"/api/projects/{pid}/brand/stoplist")
        assert r2.status_code == 200
        terms = r2.json()
        assert len(terms) == 1
        assert terms[0]["term"] == "noise.example"


@pytest.mark.asyncio
async def test_add_term_contributor_returns_403(stoplist_app):
    """POST as Contributor → 403 (Lead+ required for write)."""
    app, factory = stoplist_app
    user_id = str(uuid.uuid4())
    pid = await _seed_project(factory, user_id)
    # Contributor rank — should be rejected before FK matters
    contributor = _make_auth_user(role="Analyst", project_id=pid, project_rank=_CONTRIBUTOR_RANK, user_id=user_id)
    _patch_auth(app, contributor)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{pid}/brand/stoplist",
            json={"term": "denied.example"},
        )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_add_term_observer_returns_403(stoplist_app):
    """POST as Observer → 403 (Lead+ required for write)."""
    app, factory = stoplist_app
    user_id = str(uuid.uuid4())
    pid = await _seed_project(factory, user_id)
    # Observer rank — should be rejected before FK matters
    observer = _make_auth_user(role="Analyst", project_id=pid, project_rank=_OBSERVER_RANK, user_id=user_id)
    _patch_auth(app, observer)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{pid}/brand/stoplist",
            json={"term": "denied.example"},
        )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_add_term_duplicate_case_insensitive_returns_409(stoplist_app):
    """POST twice with different case ("Foo" then "foo") → second returns 409."""
    app, factory = stoplist_app
    lead_id = str(uuid.uuid4())
    pid = await _seed_project(factory, lead_id)
    lead = _make_auth_user(role="Analyst", project_id=pid, project_rank=_LEAD_RANK, user_id=lead_id)
    _patch_auth(app, lead)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post(
            f"/api/projects/{pid}/brand/stoplist",
            json={"term": "Foo"},
        )
        assert r1.status_code == 201, r1.text

        r2 = await client.post(
            f"/api/projects/{pid}/brand/stoplist",
            json={"term": "foo"},
        )
        assert r2.status_code == 409, r2.text


@pytest.mark.asyncio
async def test_delete_term_lead_returns_204(stoplist_app):
    """DELETE as Lead → 204; GET confirms term is gone."""
    app, factory = stoplist_app
    lead_id = str(uuid.uuid4())
    pid = await _seed_project(factory, lead_id)
    lead = _make_auth_user(role="Analyst", project_id=pid, project_rank=_LEAD_RANK, user_id=lead_id)
    _patch_auth(app, lead)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Add a term first
        r = await client.post(
            f"/api/projects/{pid}/brand/stoplist",
            json={"term": "todelete.example"},
        )
        assert r.status_code == 201, r.text
        term_id = r.json()["id"]

        # Delete it
        r_del = await client.delete(f"/api/projects/{pid}/brand/stoplist/{term_id}")
        assert r_del.status_code == 204, r_del.text

        # Confirm gone
        r_list = await client.get(f"/api/projects/{pid}/brand/stoplist")
        assert r_list.json() == []


@pytest.mark.asyncio
async def test_delete_term_contributor_returns_403(stoplist_app):
    """DELETE as Contributor → 403."""
    app, factory = stoplist_app
    lead_id = str(uuid.uuid4())
    pid = await _seed_project(factory, lead_id)

    # Add term as Lead first
    lead = _make_auth_user(role="Analyst", project_id=pid, project_rank=_LEAD_RANK, user_id=lead_id)
    _patch_auth(app, lead)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{pid}/brand/stoplist",
            json={"term": "protected.example"},
        )
        assert r.status_code == 201
        term_id = r.json()["id"]

    # Attempt delete as Contributor — Contributor's user_id doesn't need to exist
    # since the 403 fires before the route body runs
    contributor_id = str(uuid.uuid4())
    contributor = _make_auth_user(role="Analyst", project_id=pid, project_rank=_CONTRIBUTOR_RANK, user_id=contributor_id)
    _patch_auth(app, contributor)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_del = await client.delete(f"/api/projects/{pid}/brand/stoplist/{term_id}")
    assert r_del.status_code == 403, r_del.text


@pytest.mark.asyncio
async def test_delete_term_not_found_returns_404(stoplist_app):
    """DELETE non-existent term_id → 404."""
    app, factory = stoplist_app
    lead_id = str(uuid.uuid4())
    pid = await _seed_project(factory, lead_id)
    lead = _make_auth_user(role="Analyst", project_id=pid, project_rank=_LEAD_RANK, user_id=lead_id)
    _patch_auth(app, lead)

    nonexistent = uuid.uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.delete(f"/api/projects/{pid}/brand/stoplist/{nonexistent}")
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_scan_uses_project_stoplist(stoplist_app, db_engine):
    """Insert a stoplist term directly; load_runtime_stoplist_for_project returns it in frozenset."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.services.brand_stoplist import load_runtime_stoplist_for_project, is_stoplisted

    app, factory = stoplist_app
    lead_id = str(uuid.uuid4())
    pid = await _seed_project(factory, lead_id)

    # Insert stoplist term directly via raw SQL (bypasses route auth)
    async_factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with async_factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO brand_stoplist_terms (project_id, term)
                VALUES (CAST(:pid AS uuid), :term)
                """
            ),
            {"pid": str(pid), "term": "noise.example"},
        )
        await session.commit()

        # Call the async loader
        runtime_stoplist = await load_runtime_stoplist_for_project(session, pid)

    # "noise.example" must be in the returned frozenset (lowercased)
    assert "noise.example" in runtime_stoplist

    # Verify is_stoplisted works with the loaded frozenset
    assert is_stoplisted("noise.example", runtime_stoplist=runtime_stoplist) is True
    assert is_stoplisted("NOISE.EXAMPLE", runtime_stoplist=runtime_stoplist) is True
