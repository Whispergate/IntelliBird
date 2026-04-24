"""Integration tests for the brand router — terms CRUD + authority matrix (12-06)."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.integration


def _make_auth_user(
    role: str = "Admin",
    project_id: uuid.UUID | None = None,
    project_rank: int = 3,  # 3 = Lead
):
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

    def override_require_auth():
        return admin_user

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_auth] = override_require_auth
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


@pytest.mark.asyncio
async def test_post_keyword_term_as_admin_returns_201(brand_app, db_session):
    app, _factory, admin_user = brand_app
    pid = await _seed_project(db_session, admin_user.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{pid}/brand/terms",
            json={"term_type": "keyword", "value": "IntelliBirdCorp"},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["term_type"] == "keyword"
    assert body["value"] == "IntelliBirdCorp"
    assert body["mode"] == "active"
    assert body["archived"] is False


@pytest.mark.asyncio
async def test_duplicate_term_returns_409(brand_app, db_session):
    app, _factory, admin_user = brand_app
    pid = await _seed_project(db_session, admin_user.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post(
            f"/api/projects/{pid}/brand/terms",
            json={"term_type": "keyword", "value": "DupCorp"},
        )
        assert r1.status_code == 201
        r2 = await client.post(
            f"/api/projects/{pid}/brand/terms",
            json={"term_type": "keyword", "value": "DupCorp"},
        )
    assert r2.status_code == 409
    assert "already exists" in r2.json()["detail"]


@pytest.mark.asyncio
async def test_person_term_without_consent_returns_422(brand_app, db_session):
    app, _factory, admin_user = brand_app
    pid = await _seed_project(db_session, admin_user.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{pid}/brand/terms",
            json={"term_type": "person", "value": "Jane Doe", "gdpr_consent": False},
        )
    assert r.status_code == 422
    assert "gdpr_consent" in r.json()["detail"]


@pytest.mark.asyncio
async def test_person_term_admin_with_consent_succeeds(brand_app, db_session):
    app, _factory, admin_user = brand_app
    pid = await _seed_project(db_session, admin_user.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{pid}/brand/terms",
            json={"term_type": "person", "value": "John Doe", "gdpr_consent": True},
        )
    assert r.status_code == 201, r.text
    assert r.json()["term_type"] == "person"


@pytest.mark.asyncio
async def test_person_term_analyst_rejected_403(brand_app, db_session):
    """Global Analyst (no project Lead rank) → 403 on person-type per Authority matrix."""
    app, _factory, _admin = brand_app
    from app.middleware.auth import require_auth

    pid = uuid.uuid4()
    # seed project without regard for creator role
    await db_session.execute(
        text(
            """
            INSERT INTO projects (id, name, engagement_type, created_by, archived)
            VALUES (CAST(:id AS uuid), :name, 'red_team', :created_by, false)
            """
        ),
        {"id": str(pid), "name": f"brand-proj-{pid}", "created_by": str(uuid.uuid4())},
    )
    await db_session.commit()

    # Analyst with Contributor-level project rank (not Lead) — must be 403 on person
    analyst = _make_auth_user(role="Analyst", project_id=pid, project_rank=2)
    app.dependency_overrides[require_auth] = lambda: analyst

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{pid}/brand/terms",
            json={"term_type": "person", "value": "Jane Analyst", "gdpr_consent": True},
        )
    assert r.status_code == 403
    assert "Lead" in r.json()["detail"] or "Admin" in r.json()["detail"]


@pytest.mark.asyncio
async def test_observer_cannot_post_term(brand_app, db_session):
    """Project Observer (rank 1) → 403 on POST /terms."""
    app, _factory, _admin = brand_app
    from app.middleware.auth import require_auth

    pid = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO projects (id, name, engagement_type, created_by, archived)
            VALUES (CAST(:id AS uuid), :name, 'red_team', :created_by, false)
            """
        ),
        {"id": str(pid), "name": f"brand-proj-{pid}", "created_by": str(uuid.uuid4())},
    )
    await db_session.commit()

    observer = _make_auth_user(role="Viewer", project_id=pid, project_rank=1)
    app.dependency_overrides[require_auth] = lambda: observer

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{pid}/brand/terms",
            json={"term_type": "keyword", "value": "ObserverTest"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_patch_term_mode_and_archived(brand_app, db_session):
    app, _factory, admin_user = brand_app
    pid = await _seed_project(db_session, admin_user.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{pid}/brand/terms",
            json={"term_type": "keyword", "value": "PatchMe"},
        )
        assert r.status_code == 201
        term_id = r.json()["id"]

        # Flip to watch_only
        r2 = await client.patch(
            f"/api/projects/{pid}/brand/terms/{term_id}",
            json={"mode": "watch_only"},
        )
        assert r2.status_code == 200
        assert r2.json()["mode"] == "watch_only"
        assert r2.json()["archived"] is False

        # Archive
        r3 = await client.patch(
            f"/api/projects/{pid}/brand/terms/{term_id}",
            json={"archived": True},
        )
        assert r3.status_code == 200
        assert r3.json()["archived"] is True


@pytest.mark.asyncio
async def test_get_terms_default_excludes_archived(brand_app, db_session):
    app, _factory, admin_user = brand_app
    pid = await _seed_project(db_session, admin_user.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        a = await client.post(
            f"/api/projects/{pid}/brand/terms",
            json={"term_type": "keyword", "value": "AliveTerm"},
        )
        assert a.status_code == 201
        b = await client.post(
            f"/api/projects/{pid}/brand/terms",
            json={"term_type": "keyword", "value": "BuriedTerm"},
        )
        assert b.status_code == 201
        buried_id = b.json()["id"]

        await client.patch(
            f"/api/projects/{pid}/brand/terms/{buried_id}",
            json={"archived": True},
        )

        r = await client.get(f"/api/projects/{pid}/brand/terms")
        assert r.status_code == 200
        names = [row["value"] for row in r.json()]
        assert "AliveTerm" in names
        assert "BuriedTerm" not in names

        r2 = await client.get(
            f"/api/projects/{pid}/brand/terms?include_archived=true"
        )
        assert r2.status_code == 200
        names2 = [row["value"] for row in r2.json()]
        assert "AliveTerm" in names2
        assert "BuriedTerm" in names2


@pytest.mark.asyncio
async def test_patch_term_404_on_foreign_term(brand_app, db_session):
    app, _factory, admin_user = brand_app
    pid = await _seed_project(db_session, admin_user.id)

    bogus = uuid.uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/projects/{pid}/brand/terms/{bogus}",
            json={"mode": "watch_only"},
        )
    assert r.status_code == 404
