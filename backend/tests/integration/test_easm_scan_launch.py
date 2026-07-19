"""Integration tests for EASM scan launch endpoint - plan 11-05.

Covers:
  - POST /api/projects/{id}/easm/scans (passive + active modes)
  - Module safelist validation (422 for invalid/unlisted modules)
  - Active-scan gate validation (403 when gate missing/expired)
  - Concurrent-scan race prevention (409)
  - Semaphore cap (503)
  - Legacy/archived project guard (422)
  - Actor enqueueing (run_bbot_scan.send_with_options called with scan id)

Auth bypassed via dependency overrides. Redis mocked inline.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_auth_user(
    role: str = "Admin",
    project_id: uuid.UUID | None = None,
    project_rank: int = 3,
) -> "AuthUser":  # type: ignore[name-defined]  # noqa: F821
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
async def launch_app(db_engine, _migrations_applied):
    """FastAPI app with EASM + DB override + auth override."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.database import get_session
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

    app.dependency_overrides[get_session] = override_session
    yield app, factory


async def _create_project(
    db_session,
    project_id: uuid.UUID,
    name: str,
    created_by: str,
    *,
    archived: bool = False,
    active_scans_authorised: bool = False,
    scope_acknowledgement_text: str | None = None,
    active_auth_confirmed_at: datetime | None = None,
) -> None:
    await db_session.execute(text("""
        INSERT INTO projects (
            id, name, engagement_type, created_by, archived,
            active_scans_authorised, scope_acknowledgement_text, active_auth_confirmed_at
        ) VALUES (
            CAST(:id AS uuid), :name, 'red_team', :created_by, :archived,
            :active_scans_authorised, :scope_acknowledgement_text,
            :active_auth_confirmed_at
        )
    """), {
        "id": str(project_id),
        "name": name,
        "created_by": created_by,
        "archived": archived,
        "active_scans_authorised": active_scans_authorised,
        "scope_acknowledgement_text": scope_acknowledgement_text,
        "active_auth_confirmed_at": active_auth_confirmed_at,
    })
    await db_session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_launch_passive_as_contributor_returns_202(launch_app, db_session):
    """Contributor role can launch a passive scan - returns 202."""
    app, factory = launch_app
    project_id = uuid.uuid4()
    contributor_user = _make_auth_user(role="Viewer", project_id=project_id, project_rank=2)

    from app.middleware.auth import require_auth
    app.dependency_overrides[require_auth] = lambda: contributor_user

    await _create_project(db_session, project_id, f"proj-passive-{project_id}", contributor_user.id)

    with (
        patch("app.routers.easm.run_bbot_scan") as mock_actor,
        patch("app.routers.easm.redis_lib") as mock_redis_mod,
    ):
        mock_redis_instance = MagicMock()
        mock_redis_instance.get.return_value = b"0"
        mock_redis_mod.from_url.return_value = mock_redis_instance
        mock_actor.send_with_options = MagicMock()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                f"/api/projects/{project_id}/easm/scans",
                json={"scan_mode": "passive", "modules": ["crt"]},
            )

    assert r.status_code == 202, r.text
    data = r.json()
    assert data["status"] == "queued"
    assert data["scan_mode"] == "passive"
    assert data["project_id"] == str(project_id)


@pytest.mark.asyncio
async def test_launch_passive_enqueues_actor(launch_app, db_session):
    """Passive scan launch calls run_bbot_scan.send_with_options with the scan id string."""
    app, factory = launch_app
    project_id = uuid.uuid4()
    admin_user = _make_auth_user(role="Admin")

    from app.middleware.auth import require_auth
    app.dependency_overrides[require_auth] = lambda: admin_user

    await _create_project(db_session, project_id, f"proj-enqueue-{project_id}", admin_user.id)

    with (
        patch("app.routers.easm.run_bbot_scan") as mock_actor,
        patch("app.routers.easm.redis_lib") as mock_redis_mod,
    ):
        mock_redis_instance = MagicMock()
        mock_redis_instance.get.return_value = b"0"
        mock_redis_mod.from_url.return_value = mock_redis_instance
        mock_actor.send_with_options = MagicMock()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                f"/api/projects/{project_id}/easm/scans",
                json={"scan_mode": "passive", "modules": ["crt", "certspotter"]},
            )

    assert r.status_code == 202, r.text
    scan_id = r.json()["id"]
    mock_actor.send_with_options.assert_called_once()
    call_kwargs = mock_actor.send_with_options.call_args
    assert call_kwargs.kwargs["args"] == [scan_id] or (
        call_kwargs.args and call_kwargs.args[0] == [scan_id]
    ) or call_kwargs.kwargs.get("args", [None])[0] == scan_id
    # Verify time_limit is set
    assert "time_limit" in call_kwargs.kwargs


@pytest.mark.asyncio
async def test_launch_active_without_gate_returns_403(launch_app, db_session):
    """Active scan with no gate fields returns 403."""
    app, factory = launch_app
    project_id = uuid.uuid4()
    lead_user = _make_auth_user(role="Viewer", project_id=project_id, project_rank=3)

    from app.middleware.auth import require_auth
    app.dependency_overrides[require_auth] = lambda: lead_user

    # Project has no gate fields set
    await _create_project(db_session, project_id, f"proj-nogate-{project_id}", lead_user.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{project_id}/easm/scans",
            json={"scan_mode": "active", "modules": ["crt"]},
        )
    assert r.status_code == 403
    assert "gate" in r.json()["detail"].lower() or "active_scan_gate" in r.json()["detail"]


@pytest.mark.asyncio
async def test_launch_active_with_expired_gate_returns_403(launch_app, db_session):
    """Active scan with gate confirmed > TTL ago returns 403."""
    app, factory = launch_app
    from app.config import settings

    project_id = uuid.uuid4()
    lead_user = _make_auth_user(role="Viewer", project_id=project_id, project_rank=3)

    from app.middleware.auth import require_auth
    app.dependency_overrides[require_auth] = lambda: lead_user

    # Gate was confirmed well past TTL
    expired_at = datetime.now(timezone.utc) - timedelta(
        seconds=settings.BBOT_ACTIVE_AUTH_TTL_SECONDS + 3600
    )
    project_name = f"proj-expgate-{project_id}"
    await _create_project(
        db_session, project_id, project_name, lead_user.id,
        active_scans_authorised=True,
        scope_acknowledgement_text=project_name,
        active_auth_confirmed_at=expired_at,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{project_id}/easm/scans",
            json={"scan_mode": "active", "modules": ["crt"]},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_launch_active_as_contributor_returns_403(launch_app, db_session):
    """Contributor cannot launch active scans - only Lead or global Admin."""
    app, factory = launch_app
    project_id = uuid.uuid4()
    contributor_user = _make_auth_user(role="Viewer", project_id=project_id, project_rank=2)

    from app.middleware.auth import require_auth
    app.dependency_overrides[require_auth] = lambda: contributor_user

    project_name = f"proj-contrib-active-{project_id}"
    active_at = datetime.now(timezone.utc)
    await _create_project(
        db_session, project_id, project_name, contributor_user.id,
        active_scans_authorised=True,
        scope_acknowledgement_text=project_name,
        active_auth_confirmed_at=active_at,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{project_id}/easm/scans",
            json={"scan_mode": "active", "modules": ["crt"]},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_launch_with_invalid_module_returns_422_with_invalid_names(launch_app, db_session):
    """modules containing unlisted name → 422 with invalid names in detail."""
    app, factory = launch_app
    project_id = uuid.uuid4()
    admin_user = _make_auth_user(role="Admin")

    from app.middleware.auth import require_auth
    app.dependency_overrides[require_auth] = lambda: admin_user

    await _create_project(db_session, project_id, f"proj-badmod-{project_id}", admin_user.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{project_id}/easm/scans",
            json={"scan_mode": "passive", "modules": ["crt", "evil_exploit"]},
        )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "evil_exploit" in detail
    assert "not in the stable safelist" in detail


@pytest.mark.asyncio
async def test_launch_with_sublist3r_returns_422(launch_app, db_session):
    """modules=["sublist3r"] → 422 (PITFALLS §Pitfall 3 regression - removed in BBOT 2.8.x)."""
    app, factory = launch_app
    project_id = uuid.uuid4()
    admin_user = _make_auth_user(role="Admin")

    from app.middleware.auth import require_auth
    app.dependency_overrides[require_auth] = lambda: admin_user

    await _create_project(db_session, project_id, f"proj-sublist3r-{project_id}", admin_user.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{project_id}/easm/scans",
            json={"scan_mode": "passive", "modules": ["sublist3r"]},
        )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "sublist3r" in detail


@pytest.mark.asyncio
async def test_launch_when_another_scan_running_returns_409(launch_app, db_session):
    """Second POST while first scan is running → 409."""
    app, factory = launch_app
    project_id = uuid.uuid4()
    admin_user = _make_auth_user(role="Admin")

    from app.middleware.auth import require_auth
    app.dependency_overrides[require_auth] = lambda: admin_user

    await _create_project(db_session, project_id, f"proj-concurrent-{project_id}", admin_user.id)

    # Insert a running scan row directly
    await db_session.execute(text("""
        INSERT INTO easm_scans (id, project_id, status, scan_mode, modules, started_at, launched_by)
        VALUES (
            CAST(:scan_id AS uuid),
            CAST(:project_id AS uuid),
            'running'::easm_scan_status,
            'passive'::easm_scan_mode,
            ARRAY['crt'],
            now(),
            :launched_by
        )
    """), {
        "scan_id": str(uuid.uuid4()),
        "project_id": str(project_id),
        "launched_by": admin_user.id,
    })
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{project_id}/easm/scans",
            json={"scan_mode": "passive", "modules": ["crt"]},
        )
    assert r.status_code == 409
    assert "scan_already_in_progress" in r.json()["detail"]


@pytest.mark.asyncio
async def test_launch_when_semaphore_at_cap_returns_503(launch_app, db_session):
    """Redis bbot:concurrent_scans at BBOT_CONCURRENT_LIMIT → 503 with UI-SPEC copy."""
    app, factory = launch_app
    from app.config import settings

    project_id = uuid.uuid4()
    admin_user = _make_auth_user(role="Admin")

    from app.middleware.auth import require_auth
    app.dependency_overrides[require_auth] = lambda: admin_user

    await _create_project(db_session, project_id, f"proj-semaphore-{project_id}", admin_user.id)

    with (
        patch("app.routers.easm.redis_lib") as mock_redis_mod,
    ):
        mock_redis_instance = MagicMock()
        # Set counter at the concurrent limit
        mock_redis_instance.get.return_value = str(settings.BBOT_CONCURRENT_LIMIT).encode()
        mock_redis_mod.from_url.return_value = mock_redis_instance

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                f"/api/projects/{project_id}/easm/scans",
                json={"scan_mode": "passive", "modules": ["crt"]},
            )

    assert r.status_code == 503
    # UI-SPEC byte-exact copy
    assert "Scan limit reached." in r.json()["detail"]
    assert "Wait for a running scan to finish" in r.json()["detail"]


@pytest.mark.asyncio
async def test_launch_against_legacy_project_returns_422(launch_app, db_session):
    """Launching a scan against the LEGACY_PROJECT_ID sentinel → 422."""
    from app.models.projects import LEGACY_PROJECT_ID

    app, factory = launch_app
    admin_user = _make_auth_user(role="Admin")

    from app.middleware.auth import require_auth
    app.dependency_overrides[require_auth] = lambda: admin_user

    with (
        patch("app.routers.easm.redis_lib") as mock_redis_mod,
    ):
        mock_redis_instance = MagicMock()
        mock_redis_instance.get.return_value = b"0"
        mock_redis_mod.from_url.return_value = mock_redis_instance

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                f"/api/projects/{LEGACY_PROJECT_ID}/easm/scans",
                json={"scan_mode": "passive", "modules": ["crt"]},
            )
    assert r.status_code == 422
    assert "archived or legacy" in r.json()["detail"]


@pytest.mark.asyncio
async def test_launch_against_archived_project_returns_422(launch_app, db_session):
    """Launching a scan against an archived project → 422."""
    app, factory = launch_app
    project_id = uuid.uuid4()
    admin_user = _make_auth_user(role="Admin")

    from app.middleware.auth import require_auth
    app.dependency_overrides[require_auth] = lambda: admin_user

    await _create_project(
        db_session, project_id, f"proj-archived-{project_id}", admin_user.id,
        archived=True,
    )

    with (
        patch("app.routers.easm.redis_lib") as mock_redis_mod,
    ):
        mock_redis_instance = MagicMock()
        mock_redis_instance.get.return_value = b"0"
        mock_redis_mod.from_url.return_value = mock_redis_instance

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                f"/api/projects/{project_id}/easm/scans",
                json={"scan_mode": "passive", "modules": ["crt"]},
            )
    assert r.status_code == 422
    assert "archived or legacy" in r.json()["detail"]
