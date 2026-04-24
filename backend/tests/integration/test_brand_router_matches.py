"""Integration tests for the brand router — matches + lifecycle + extend + suppression-review (12-06)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.integration


def _make_auth_user(
    role: str = "Admin",
    project_id: uuid.UUID | None = None,
    project_rank: int = 3,
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


async def _seed_project_term_match(
    db_session,
    admin_user_id: str,
    *,
    severity: str = "high",
    match_source: str = "fts",
    matched_value: str | None = None,
    lifecycle: str = "new",
    dismiss_until: datetime | None = None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Return (project_id, term_id, match_id)."""
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
    tid = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO brand_terms (id, project_id, term_type, value, mode, archived)
            VALUES (CAST(:id AS uuid), CAST(:pid AS uuid), 'keyword', :value, 'active', false)
            """
        ),
        {"id": str(tid), "pid": str(pid), "value": f"term-{tid.hex[:8]}"},
    )
    mid = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO brand_matches (
                id, project_id, brand_term_id, matched_value, match_source,
                severity, first_seen, last_seen, lifecycle_status, dismiss_until
            ) VALUES (
                CAST(:id AS uuid), CAST(:pid AS uuid), CAST(:tid AS uuid),
                :mv, :src, :sev, now(), now(), :lc, :du
            )
            """
        ),
        {
            "id": str(mid),
            "pid": str(pid),
            "tid": str(tid),
            "mv": matched_value or f"evil-{mid.hex[:8]}.com",
            "src": match_source,
            "sev": severity,
            "lc": lifecycle,
            "du": dismiss_until,
        },
    )
    await db_session.commit()
    return pid, tid, mid


@pytest.mark.asyncio
async def test_list_matches_returns_dashboard_response(brand_app, db_session):
    app, _factory, admin_user = brand_app
    pid, _tid, _mid = await _seed_project_term_match(db_session, admin_user.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/api/projects/{pid}/brand/matches")
    assert r.status_code == 200
    body = r.json()
    assert "matches" in body
    assert "has_expiring_dismissals" in body
    assert "has_recent_auto_downgrade" in body
    assert "recent_auto_downgrade_terms" in body
    assert len(body["matches"]) == 1


@pytest.mark.asyncio
async def test_list_matches_severity_filter(brand_app, db_session):
    app, _factory, admin_user = brand_app
    pid, _tid, _mid = await _seed_project_term_match(
        db_session, admin_user.id, severity="high"
    )
    await _seed_project_term_match(
        db_session, admin_user.id, severity="low"
    )  # different project, shouldn't appear

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            f"/api/projects/{pid}/brand/matches?severity=high"
        )
    assert r.status_code == 200
    assert all(m["severity"] == "high" for m in r.json()["matches"])


@pytest.mark.asyncio
async def test_list_matches_hides_dismissed_by_default(brand_app, db_session):
    app, _factory, admin_user = brand_app
    pid, _tid, _mid = await _seed_project_term_match(
        db_session,
        admin_user.id,
        lifecycle="dismissed",
        dismiss_until=datetime.now(timezone.utc) + timedelta(days=30),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/api/projects/{pid}/brand/matches")
        assert r.status_code == 200
        assert r.json()["matches"] == []

        r2 = await client.get(
            f"/api/projects/{pid}/brand/matches?include_dismissed=true"
        )
        assert r2.status_code == 200
        assert len(r2.json()["matches"]) == 1


@pytest.mark.asyncio
async def test_patch_match_dismissed_defaults_30d(brand_app, db_session):
    app, _factory, admin_user = brand_app
    pid, _tid, mid = await _seed_project_term_match(db_session, admin_user.id)

    before = datetime.now(timezone.utc)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/projects/{pid}/brand/matches/{mid}",
            json={"lifecycle_status": "dismissed"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lifecycle_status"] == "dismissed"
    dismiss = datetime.fromisoformat(body["dismiss_until"].replace("Z", "+00:00"))
    assert before + timedelta(days=29, hours=23) <= dismiss <= before + timedelta(days=30, hours=1)


@pytest.mark.asyncio
async def test_patch_match_new_clears_dismiss_until(brand_app, db_session):
    app, _factory, admin_user = brand_app
    pid, _tid, mid = await _seed_project_term_match(
        db_session,
        admin_user.id,
        lifecycle="dismissed",
        dismiss_until=datetime.now(timezone.utc) + timedelta(days=30),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/projects/{pid}/brand/matches/{mid}",
            json={"lifecycle_status": "new"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["lifecycle_status"] == "new"
    assert body["dismiss_until"] is None


@pytest.mark.asyncio
async def test_observer_cannot_patch_match(brand_app, db_session):
    app, _factory, _admin = brand_app
    from app.middleware.auth import require_auth

    pid, _tid, mid = await _seed_project_term_match(db_session, str(uuid.uuid4()))

    observer = _make_auth_user(role="Viewer", project_id=pid, project_rank=1)
    app.dependency_overrides[require_auth] = lambda: observer

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/projects/{pid}/brand/matches/{mid}",
            json={"lifecycle_status": "confirmed"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_extend_with_explicit_days_updates_dismiss_until(brand_app, db_session):
    app, _factory, admin_user = brand_app
    pid, _tid, mid = await _seed_project_term_match(
        db_session,
        admin_user.id,
        lifecycle="dismissed",
        dismiss_until=datetime.now(timezone.utc) + timedelta(days=1),
    )

    before = datetime.now(timezone.utc)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{pid}/brand/matches/{mid}/extend",
            json={"extend_days": 60, "let_resurface": False},
        )
    assert r.status_code == 200
    body = r.json()
    new_du = datetime.fromisoformat(body["dismiss_until"].replace("Z", "+00:00"))
    assert before + timedelta(days=59, hours=23) <= new_du <= before + timedelta(days=60, hours=1)


@pytest.mark.asyncio
async def test_extend_null_days_means_indefinite(brand_app, db_session):
    app, _factory, admin_user = brand_app
    pid, _tid, mid = await _seed_project_term_match(
        db_session,
        admin_user.id,
        lifecycle="dismissed",
        dismiss_until=datetime.now(timezone.utc) + timedelta(days=1),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{pid}/brand/matches/{mid}/extend",
            json={"extend_days": None, "let_resurface": False},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["dismiss_until"] is None
    # status unchanged
    assert body["lifecycle_status"] == "dismissed"


@pytest.mark.asyncio
async def test_extend_let_resurface_resets_to_new(brand_app, db_session):
    app, _factory, admin_user = brand_app
    pid, _tid, mid = await _seed_project_term_match(
        db_session,
        admin_user.id,
        lifecycle="dismissed",
        dismiss_until=datetime.now(timezone.utc) + timedelta(days=10),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{pid}/brand/matches/{mid}/extend",
            json={"extend_days": None, "let_resurface": True},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["lifecycle_status"] == "new"
    assert body["dismiss_until"] is None


@pytest.mark.asyncio
async def test_suppression_review_returns_only_upcoming(brand_app, db_session):
    app, _factory, admin_user = brand_app

    # Expiring in 3 days — SHOULD appear
    pid, _tid, _mid = await _seed_project_term_match(
        db_session,
        admin_user.id,
        lifecycle="dismissed",
        dismiss_until=datetime.now(timezone.utc) + timedelta(days=3),
    )
    # Same project — add another match expiring in 30 days (should NOT appear)
    await db_session.execute(
        text(
            """
            INSERT INTO brand_matches (
                id, project_id, brand_term_id, matched_value, match_source,
                severity, first_seen, last_seen, lifecycle_status, dismiss_until
            )
            SELECT gen_random_uuid(), bt.project_id, bt.id, 'far-future.com',
                   'fts', 'high', now(), now(), 'dismissed',
                   now() + INTERVAL '30 days'
            FROM brand_terms bt WHERE bt.project_id = CAST(:pid AS uuid) LIMIT 1
            """
        ),
        {"pid": str(pid)},
    )
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/api/projects/{pid}/brand/suppression-review")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    # All returned dismiss_until within 7 days
    for row in rows:
        du = datetime.fromisoformat(row["dismiss_until"].replace("Z", "+00:00"))
        assert du < datetime.now(timezone.utc) + timedelta(days=7)


@pytest.mark.asyncio
async def test_has_expiring_dismissals_banner_flag(brand_app, db_session):
    app, _factory, admin_user = brand_app
    pid, _tid, _mid = await _seed_project_term_match(
        db_session,
        admin_user.id,
        lifecycle="dismissed",
        dismiss_until=datetime.now(timezone.utc) + timedelta(days=3),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(
            f"/api/projects/{pid}/brand/matches?include_dismissed=true"
        )
    assert r.status_code == 200
    body = r.json()
    assert body["has_expiring_dismissals"] is True


@pytest.mark.asyncio
async def test_has_recent_auto_downgrade_banner_flag(brand_app, db_session):
    app, _factory, admin_user = brand_app
    pid, tid, _mid = await _seed_project_term_match(db_session, admin_user.id)

    # Flip term to watch_only
    await db_session.execute(
        text("UPDATE brand_terms SET mode='watch_only' WHERE id = CAST(:tid AS uuid)"),
        {"tid": str(tid)},
    )
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/api/projects/{pid}/brand/matches")
    assert r.status_code == 200
    body = r.json()
    assert body["has_recent_auto_downgrade"] is True
    assert len(body["recent_auto_downgrade_terms"]) >= 1
