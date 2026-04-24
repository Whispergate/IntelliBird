"""PROD-02 — EASM active-scan gate pentest.

Penetration-style assertion that the active-scan two-factor gate at
POST /api/projects/{project_id}/easm/scans cannot be bypassed by a
direct HTTP POST. Covers the gate-missing matrix, a tampered-JWT
(reduced role/rank) negative case, and a passive-mode positive control
to isolate gate-specific rejection from routing/auth regressions.

Gate fields on the Project row (migration 011):
  - active_scans_authorised            (bool)
  - scope_acknowledgement_text         (text, must match project.name)
  - active_auth_confirmed_at           (timestamp, within BBOT_ACTIVE_AUTH_TTL_SECONDS)

Server-side gate is in backend/app/routers/easm.py::_is_active_gate_valid —
this pentest re-reads that contract via the public API.

All POSTs go through httpx + ASGITransport (no UI helpers). Auth identity is
injected via FastAPI dependency_overrides[require_auth] to simulate the
claim shape that AuthMiddleware would populate — the "tampered JWT" case
models a token whose role/project-rank has been downgraded post-issuance
and is therefore equivalent to an attacker who has rewritten the claim.
"""
from __future__ import annotations

import os

# Settings (pydantic-settings) requires these at import time; mirror the
# pattern used by test_two_project_fixture_smoke.py. setdefault keeps any
# caller-provided values intact (e.g. when the full suite already set them).
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)
os.environ.setdefault("SECRET_KEY", "s" * 64)

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_auth_user(
    *,
    role: str = "Viewer",
    project_id: uuid.UUID | None = None,
    project_rank: int = 3,  # 3 = Lead (active-scan authority)
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
    """FastAPI app mounting only the EASM router + DB override. Mirrors the
    test_easm_scan_launch harness so the two files share a contract."""
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
    active_scans_authorised: bool = False,
    scope_acknowledgement_text: str | None = None,
    active_auth_confirmed_at: datetime | None = None,
) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO projects (
                id, name, engagement_type, created_by, archived,
                active_scans_authorised, scope_acknowledgement_text, active_auth_confirmed_at
            ) VALUES (
                CAST(:id AS uuid), :name, 'red_team', :created_by, false,
                :asa, :sat, :aac
            )
            """
        ),
        {
            "id": str(project_id),
            "name": name,
            "created_by": created_by,
            "asa": active_scans_authorised,
            "sat": scope_acknowledgement_text,
            "aac": active_auth_confirmed_at,
        },
    )
    await db_session.commit()


def _valid_gate_kwargs(project_name: str) -> dict:
    """Return kwargs for _create_project with a fully-valid active-scan gate."""
    return dict(
        active_scans_authorised=True,
        scope_acknowledgement_text=project_name,
        active_auth_confirmed_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Gate-missing matrix — 4 parametrized cases
# ---------------------------------------------------------------------------

GATE_FIELDS: tuple[str, str, str] = (
    "active_scans_authorised",
    "scope_acknowledgement_text",
    "active_auth_confirmed_at",
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing_fields",
    [
        pytest.param(("active_scans_authorised",), id="missing-authorised-flag"),
        pytest.param(("scope_acknowledgement_text",), id="missing-scope-ack"),
        pytest.param(("active_auth_confirmed_at",), id="missing-confirmed-at"),
        pytest.param(GATE_FIELDS, id="all-three-missing"),
    ],
)
async def test_active_scan_rejected_when_gate_field_missing(
    easm_app, db_session, missing_fields: tuple[str, ...]
):
    """Active scan POST with any subset of gate fields missing on the project → 403.

    Caller has full active-scan authority (project Lead) so the rejection is
    attributable to the gate check, not the role gate.
    """
    app, _ = easm_app
    project_id = uuid.uuid4()
    project_name = f"prod02-missing-{project_id}"

    # Start from a fully-valid gate, then blank the parametrized fields.
    gate_kwargs = _valid_gate_kwargs(project_name)
    for field in missing_fields:
        if field == "active_scans_authorised":
            gate_kwargs["active_scans_authorised"] = False
        else:
            gate_kwargs[field] = None

    lead_user = _make_auth_user(role="Viewer", project_id=project_id, project_rank=3)

    from app.middleware.auth import require_auth
    app.dependency_overrides[require_auth] = lambda: lead_user

    await _create_project(
        db_session, project_id, project_name, lead_user.id, **gate_kwargs
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{project_id}/easm/scans",
            json={"scan_mode": "active", "modules": ["crt"]},
        )

    assert r.status_code == 403, (
        f"expected 403 for missing={missing_fields}; got {r.status_code} {r.text}"
    )
    body = r.json()
    detail = (body.get("detail") or "").lower()
    # Either the gate-specific detail or a defence-in-depth role rejection is
    # acceptable — both prove the active scan was NOT dispatched.
    assert "gate" in detail or "active_scan_gate" in detail or "active" in detail, (
        f"expected gate-related 403 detail; got: {body}"
    )


# ---------------------------------------------------------------------------
# Tampered-JWT case — reduced role/rank cannot launch even with valid gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_active_scan_rejected_with_tampered_jwt(easm_app, db_session):
    """A caller whose claim has been downgraded to an Observer (rank=1, role='Viewer')
    cannot launch an active scan even when the project's gate is fully valid.

    Models a post-issuance claim-tamper where an attacker trims their
    authority. The server derives rank + role exclusively from the claim
    (see AuthMiddleware step 6 + easm.py authority check) so the outcome
    MUST be 403 regardless of request body contents.
    """
    app, _ = easm_app
    project_id = uuid.uuid4()
    project_name = f"prod02-tamper-{project_id}"

    tampered_user = _make_auth_user(
        role="Viewer",           # downgraded from Admin
        project_id=project_id,
        project_rank=1,          # Observer — below Lead threshold for active launch
    )

    from app.middleware.auth import require_auth
    app.dependency_overrides[require_auth] = lambda: tampered_user

    # Project has a FULLY VALID gate — so any 403 is pinned to authority + gate
    # being non-bypassable via direct HTTP.
    await _create_project(
        db_session,
        project_id,
        project_name,
        tampered_user.id,
        **_valid_gate_kwargs(project_name),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/projects/{project_id}/easm/scans",
            json={"scan_mode": "active", "modules": ["crt"]},
        )

    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# Positive control — passive scan with valid caller returns 2xx
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_passive_scan_positive_control_returns_2xx(easm_app, db_session):
    """Positive control: a valid caller launching a PASSIVE scan reaches the queue.

    Isolates gate-specific rejection from endpoint unreachability, routing
    breakage, or generic auth regressions. If this fails, the gate-missing
    matrix above might be passing for the wrong reason (e.g. 403 on every
    path because the endpoint itself is broken).
    """
    app, _ = easm_app
    project_id = uuid.uuid4()
    project_name = f"prod02-positive-{project_id}"

    admin_user = _make_auth_user(role="Admin")  # global Admin → passive OK

    from app.middleware.auth import require_auth
    app.dependency_overrides[require_auth] = lambda: admin_user

    # No gate needed for passive — create the project without gate fields set.
    await _create_project(db_session, project_id, project_name, admin_user.id)

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

    assert r.status_code in (200, 202), (
        f"positive-control passive scan must succeed; got {r.status_code} {r.text}"
    )
    body = r.json()
    assert body["scan_mode"] == "passive"
    assert body["project_id"] == str(project_id)
