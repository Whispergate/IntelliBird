"""Integration tests for the EASM router — plan 11-05.

Covers:
  - GET /api/easm/safelist
  - GET /api/projects/{id}/easm/scans (list — empty)
  - GET /api/projects/{id}/easm/findings (list — empty, filtered)
  - PATCH /api/projects/{id}/easm/findings/{id} (lifecycle actions)
  - Observer blocked from PATCH (authority matrix)

Uses testcontainers-backed db_session + _migrations_applied from conftest.py.
Auth is bypassed via app.dependency_overrides (same pattern as Phase 10).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers — mint an AuthUser and build a test app with overrides
# ---------------------------------------------------------------------------

def _make_auth_user(
    role: str = "Admin",
    project_id: uuid.UUID | None = None,
    project_rank: int = 3,  # 3 = Lead
) -> "AuthUser":  # type: ignore[name-defined]
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
async def easm_app(db_engine, _migrations_applied):
    """Minimal FastAPI app with EASM routes + DB + auth overrides."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.database import get_session
    from app.middleware.auth import require_auth
    from app.routers.easm import router as easm_router
    from app.routers.easm import safelist_router as easm_safelist_router
    from fastapi import FastAPI

    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    app = FastAPI()
    app.include_router(easm_safelist_router, prefix="/api")
    app.include_router(easm_router, prefix="/api")

    async def override_session():
        async with factory() as session:
            yield session

    # Default: Admin user (no project needed for safelist)
    admin_user = _make_auth_user(role="Admin")

    def override_require_auth():
        return admin_user

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_auth] = override_require_auth
    yield app, factory, admin_user


# ---------------------------------------------------------------------------
# Safelist endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safelist_endpoint_returns_frozen_modules(easm_app):
    """GET /api/easm/safelist — 200; modules non-empty; contains 'crt'; no 'sublist3r'."""
    app, factory, _user = easm_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/easm/safelist")
    assert r.status_code == 200
    data = r.json()
    assert "modules" in data
    assert isinstance(data["modules"], list)
    assert len(data["modules"]) > 0
    # Module name is "crt" (not "crt.sh") — PITFALLS §Pitfall 3
    assert "crt" in data["modules"]
    # sublist3r removed from BBOT 2.8.x — must not be in safelist (PITFALLS §Pitfall 3)
    assert "sublist3r" not in data["modules"]


@pytest.mark.asyncio
async def test_safelist_includes_bbot_version(easm_app):
    """GET /api/easm/safelist — bbot_version field present and matches pinned version."""
    from app.services.bbot_safelist import BBOT_VERSION

    app, factory, _user = easm_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/easm/safelist")
    assert r.status_code == 200
    data = r.json()
    assert data["bbot_version"] == BBOT_VERSION
    assert "requires_credentials" in data


# ---------------------------------------------------------------------------
# List scans — empty
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_scans_empty_returns_empty_list(easm_app, db_session):
    """GET /api/projects/{id}/easm/scans — fresh project has no scans."""
    app, factory, admin_user = easm_app
    project_id = uuid.uuid4()
    # Insert a project row
    await db_session.execute(text("""
        INSERT INTO projects (id, name, engagement_type, created_by, archived)
        VALUES (CAST(:id AS uuid), :name, 'red_team', :created_by, false)
    """), {"id": str(project_id), "name": f"test-project-{project_id}", "created_by": admin_user.id})
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/api/projects/{project_id}/easm/scans")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# List findings — empty
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_findings_empty_returns_empty_list(easm_app, db_session):
    """GET /api/projects/{id}/easm/findings — fresh project returns empty list."""
    app, factory, admin_user = easm_app
    project_id = uuid.uuid4()
    await db_session.execute(text("""
        INSERT INTO projects (id, name, engagement_type, created_by, archived)
        VALUES (CAST(:id AS uuid), :name, 'red_team', :created_by, false)
    """), {"id": str(project_id), "name": f"test-proj-findings-{project_id}", "created_by": admin_user.id})
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/api/projects/{project_id}/easm/findings")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# Finding lifecycle PATCH tests
# ---------------------------------------------------------------------------

async def _seed_scan_and_finding(db_session, project_id: uuid.UUID, admin_user_id: str) -> uuid.UUID:
    """Insert an easm_scan + easm_finding row; return finding_id."""
    scan_id = uuid.uuid4()
    await db_session.execute(text("""
        INSERT INTO easm_scans (id, project_id, status, scan_mode, modules, started_at, launched_by)
        VALUES (
            CAST(:scan_id AS uuid),
            CAST(:project_id AS uuid),
            'finished'::easm_scan_status,
            'passive'::easm_scan_mode,
            ARRAY['crt'],
            now(),
            :launched_by
        )
    """), {"scan_id": str(scan_id), "project_id": str(project_id), "launched_by": admin_user_id})

    finding_id = uuid.uuid4()
    content_hash = uuid.uuid4().hex
    await db_session.execute(text("""
        INSERT INTO easm_findings (
            id, project_id, scan_id, bbot_event_type, canonical_target,
            severity, module, raw_bbot, content_hash, first_seen, last_seen,
            lifecycle_status
        ) VALUES (
            CAST(:id AS uuid),
            CAST(:project_id AS uuid),
            CAST(:scan_id AS uuid),
            'VULNERABILITY',
            'sub.example.com',
            'high'::easm_severity,
            'nuclei',
            '{"data": {"host": "sub.example.com"}}'::jsonb,
            :content_hash,
            now(),
            now(),
            'new'::easm_lifecycle
        )
    """), {
        "id": str(finding_id),
        "project_id": str(project_id),
        "scan_id": str(scan_id),
        "content_hash": content_hash,
    })
    await db_session.commit()
    return finding_id


@pytest.mark.asyncio
async def test_patch_finding_to_confirmed(easm_app, db_session):
    """PATCH lifecycle_status=confirmed → 200 + DB updated."""
    app, factory, admin_user = easm_app
    project_id = uuid.uuid4()
    await db_session.execute(text("""
        INSERT INTO projects (id, name, engagement_type, created_by, archived)
        VALUES (CAST(:id AS uuid), :name, 'red_team', :created_by, false)
    """), {"id": str(project_id), "name": f"proj-patch-{project_id}", "created_by": admin_user.id})
    await db_session.commit()

    finding_id = await _seed_scan_and_finding(db_session, project_id, admin_user.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/projects/{project_id}/easm/findings/{finding_id}",
            json={"lifecycle_status": "confirmed"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["lifecycle_status"] == "confirmed"
    assert data["dismiss_until"] is None


@pytest.mark.asyncio
async def test_patch_finding_to_dismissed_sets_dismiss_until_30d(easm_app, db_session):
    """PATCH lifecycle_status=dismissed → dismiss_until ≈ NOW()+30d."""
    app, factory, admin_user = easm_app
    project_id = uuid.uuid4()
    await db_session.execute(text("""
        INSERT INTO projects (id, name, engagement_type, created_by, archived)
        VALUES (CAST(:id AS uuid), :name, 'red_team', :created_by, false)
    """), {"id": str(project_id), "name": f"proj-dismiss-{project_id}", "created_by": admin_user.id})
    await db_session.commit()

    finding_id = await _seed_scan_and_finding(db_session, project_id, admin_user.id)

    before = datetime.now(timezone.utc)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/projects/{project_id}/easm/findings/{finding_id}",
            json={"lifecycle_status": "dismissed"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["lifecycle_status"] == "dismissed"
    assert data["dismiss_until"] is not None

    # dismiss_until should be ~30d from now
    dismiss_until = datetime.fromisoformat(data["dismiss_until"].replace("Z", "+00:00"))
    expected_min = before + timedelta(days=29, hours=23)
    expected_max = before + timedelta(days=30, hours=1)
    assert expected_min <= dismiss_until <= expected_max, (
        f"dismiss_until {dismiss_until} not within 30d window"
    )


@pytest.mark.asyncio
async def test_patch_finding_to_new_clears_dismiss_until(easm_app, db_session):
    """PATCH lifecycle_status=new → dismiss_until is NULL."""
    app, factory, admin_user = easm_app
    project_id = uuid.uuid4()
    await db_session.execute(text("""
        INSERT INTO projects (id, name, engagement_type, created_by, archived)
        VALUES (CAST(:id AS uuid), :name, 'red_team', :created_by, false)
    """), {"id": str(project_id), "name": f"proj-tonew-{project_id}", "created_by": admin_user.id})
    await db_session.commit()

    finding_id = await _seed_scan_and_finding(db_session, project_id, admin_user.id)

    # First dismiss it
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/projects/{project_id}/easm/findings/{finding_id}",
            json={"lifecycle_status": "dismissed"},
        )
        assert r.status_code == 200
        # Then flip to new
        r2 = await client.patch(
            f"/api/projects/{project_id}/easm/findings/{finding_id}",
            json={"lifecycle_status": "new"},
        )
    assert r2.status_code == 200
    data = r2.json()
    assert data["lifecycle_status"] == "new"
    assert data["dismiss_until"] is None


@pytest.mark.asyncio
async def test_observer_cannot_patch_finding(easm_app, db_session):
    """Observer role → 403 with UI-SPEC canonical copy."""
    app, factory, _admin = easm_app
    from app.middleware.auth import require_auth

    project_id = uuid.uuid4()
    # Create an Observer-rank user for this project
    observer_user = _make_auth_user(role="Viewer", project_id=project_id, project_rank=1)

    def override_observer():
        return observer_user

    app.dependency_overrides[require_auth] = override_observer

    await db_session.execute(text("""
        INSERT INTO projects (id, name, engagement_type, created_by, archived)
        VALUES (CAST(:id AS uuid), :name, 'red_team', :created_by, false)
    """), {"id": str(project_id), "name": f"proj-observer-{project_id}", "created_by": str(uuid.uuid4())})
    await db_session.commit()

    finding_id = await _seed_scan_and_finding(db_session, project_id, str(uuid.uuid4()))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/projects/{project_id}/easm/findings/{finding_id}",
            json={"lifecycle_status": "confirmed"},
        )
    assert r.status_code == 403
    # UI-SPEC byte-exact copy
    assert "Observers cannot modify finding status." in r.json()["detail"]

    # Restore admin override
    app.dependency_overrides[require_auth] = lambda: _admin


@pytest.mark.asyncio
async def test_list_findings_excludes_dismissed_by_default(easm_app, db_session):
    """Default list excludes dismissed findings."""
    app, factory, admin_user = easm_app
    project_id = uuid.uuid4()
    await db_session.execute(text("""
        INSERT INTO projects (id, name, engagement_type, created_by, archived)
        VALUES (CAST(:id AS uuid), :name, 'red_team', :created_by, false)
    """), {"id": str(project_id), "name": f"proj-excl-{project_id}", "created_by": admin_user.id})
    await db_session.commit()

    finding_id = await _seed_scan_and_finding(db_session, project_id, admin_user.id)

    # Dismiss the finding
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/projects/{project_id}/easm/findings/{finding_id}",
            json={"lifecycle_status": "dismissed"},
        )
        assert r.status_code == 200

        # Default list — should not include dismissed
        r2 = await client.get(f"/api/projects/{project_id}/easm/findings")
    assert r2.status_code == 200
    ids = [f["id"] for f in r2.json()]
    assert str(finding_id) not in ids


@pytest.mark.asyncio
async def test_list_findings_include_dismissed_true_returns_all(easm_app, db_session):
    """include_dismissed=true returns dismissed findings too."""
    app, factory, admin_user = easm_app
    project_id = uuid.uuid4()
    await db_session.execute(text("""
        INSERT INTO projects (id, name, engagement_type, created_by, archived)
        VALUES (CAST(:id AS uuid), :name, 'red_team', :created_by, false)
    """), {"id": str(project_id), "name": f"proj-incl-{project_id}", "created_by": admin_user.id})
    await db_session.commit()

    finding_id = await _seed_scan_and_finding(db_session, project_id, admin_user.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Dismiss it
        await client.patch(
            f"/api/projects/{project_id}/easm/findings/{finding_id}",
            json={"lifecycle_status": "dismissed"},
        )
        # List with include_dismissed=true
        r = await client.get(
            f"/api/projects/{project_id}/easm/findings",
            params={"include_dismissed": "true"},
        )
    assert r.status_code == 200
    ids = [f["id"] for f in r.json()]
    assert str(finding_id) in ids
