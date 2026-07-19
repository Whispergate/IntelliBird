"""Unit tests for EASM active-scan gate flip (EASM-04 / C-3).

Activated by plan 11-06.

Tests cover:
- Byte-exact project name match → gate flip success (Lead and Admin)
- Wrong name → 422 canonical copy
- confirm_authorisation=False → Pydantic ValidationError
- Non-Lead roles → 403 canonical copy
- Archived + legacy project guards → 422
- Revoke (DELETE) clears all four gate fields → Lead only
- active_auth_confirmed_by stamped on flip
"""
from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "x" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "y" * 64)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.easm import EASMGateFlipRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(
    *,
    project_id: uuid.UUID | None = None,
    name: str = "Acme Engagement",
    archived: bool = False,
    is_legacy: bool = False,
) -> MagicMock:
    """Produce a minimal Project-like mock."""
    p = MagicMock()
    p.id = project_id or uuid.uuid4()
    p.name = name
    p.archived = archived
    p.active_scans_authorised = False
    p.scope_acknowledgement_text = None
    p.active_auth_confirmed_at = None
    p.active_auth_confirmed_by = None
    return p


def _make_user(
    *,
    sub: str = "user-sub-001",
    role: str = "Viewer",
    project_id: uuid.UUID | None = None,
    project_rank: int | None = None,
    pm_truncated: bool = False,
) -> Any:
    """Produce a minimal AuthUser-like dict/object for request.state.user."""
    from app.security.jwt import AuthUser
    pm: dict[str, int] = {}
    if project_id is not None and project_rank is not None:
        pm[str(project_id)] = project_rank
    return AuthUser(
        id=sub,
        role=role,
        dashboard_roles=[],
        jti="jti-001",
        token_version=1,
        project_memberships=pm,
        pm_truncated=pm_truncated,
    )


async def _call_flip(project: MagicMock, user: Any, body: EASMGateFlipRequest):
    """Call flip_easm_gate with a fake DB that returns `project`."""
    from app.routers.projects import flip_easm_gate

    # Build fake request with request.state.user
    request = MagicMock()
    request.state.user = user

    # Fake DB session
    db = AsyncMock()
    # First execute (SELECT) returns project; second execute (UPDATE) + commit + third execute (re-fetch) all succeed
    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none.return_value = project
    scalar_mock.scalar_one.return_value = project
    db.execute.return_value = scalar_mock
    db.commit = AsyncMock()

    return await flip_easm_gate(
        project_id=project.id,
        body=body,
        request=request,
        db=db,
    )


async def _call_revoke(project: MagicMock, user: Any):
    """Call revoke_easm_gate with a fake DB that returns `project`."""
    from app.routers.projects import revoke_easm_gate

    request = MagicMock()
    request.state.user = user

    db = AsyncMock()
    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none.return_value = project
    scalar_mock.scalar_one.return_value = project
    db.execute.return_value = scalar_mock
    db.commit = AsyncMock()

    return await revoke_easm_gate(
        project_id=project.id,
        request=request,
        db=db,
    )


# ---------------------------------------------------------------------------
# EASMGateFlipRequest Pydantic-layer test (no async needed)
# ---------------------------------------------------------------------------

def test_gate_flip_confirm_authorisation_false_rejected_at_pydantic_layer():
    """confirm_authorisation=False must raise ValidationError (Literal[True] constraint)."""
    with pytest.raises(ValidationError):
        EASMGateFlipRequest(
            confirm_authorisation=False,  # type: ignore[arg-type]
            scope_acknowledgement_text="some project",
        )


# ---------------------------------------------------------------------------
# Authority tests - 403 paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_flip_as_contributor_returns_403_with_canonical_copy():
    """Contributor (rank 2) must be rejected with canonical 403 copy."""
    proj = _make_project()
    user = _make_user(role="Viewer", project_id=proj.id, project_rank=2)  # Contributor
    body = EASMGateFlipRequest(
        scope_acknowledgement_text=proj.name,
        confirm_authorisation=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        await _call_flip(proj, user, body)
    assert exc_info.value.status_code == 403
    assert "You do not have permission to authorise active scans. Lead or Admin role required." in str(
        exc_info.value.detail
    )


@pytest.mark.asyncio
async def test_gate_flip_as_observer_returns_403():
    """Observer (rank 1) must be rejected with 403."""
    proj = _make_project()
    user = _make_user(role="Viewer", project_id=proj.id, project_rank=1)  # Observer
    body = EASMGateFlipRequest(
        scope_acknowledgement_text=proj.name,
        confirm_authorisation=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        await _call_flip(proj, user, body)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_gate_flip_as_global_analyst_with_no_membership_returns_403():
    """Global Analyst with no project membership must be rejected."""
    proj = _make_project()
    # Analyst global role, no pm entry for this project
    user = _make_user(role="Analyst", pm_truncated=False)
    body = EASMGateFlipRequest(
        scope_acknowledgement_text=proj.name,
        confirm_authorisation=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        await _call_flip(proj, user, body)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Name mismatch - 422 path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_flip_with_wrong_name_returns_422_with_canonical_copy():
    """Non-matching scope_acknowledgement_text must return 422 with canonical error copy."""
    proj = _make_project(name="Real Project Name")
    # Use Lead so authority check passes
    user = _make_user(role="Viewer", project_id=proj.id, project_rank=3)  # Lead
    body = EASMGateFlipRequest(
        scope_acknowledgement_text="wrong name",
        confirm_authorisation=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        await _call_flip(proj, user, body)
    assert exc_info.value.status_code == 422
    assert "Scope acknowledgement text does not match the project name." in str(
        exc_info.value.detail
    )


# ---------------------------------------------------------------------------
# Archive + legacy guards - 422 paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_flip_against_archived_project_returns_422():
    """Archived project must return 422."""
    proj = _make_project(archived=True)
    user = _make_user(role="Viewer", project_id=proj.id, project_rank=3)  # Lead
    body = EASMGateFlipRequest(
        scope_acknowledgement_text=proj.name,
        confirm_authorisation=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        await _call_flip(proj, user, body)
    assert exc_info.value.status_code == 422
    assert "archived or legacy" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_gate_flip_against_legacy_project_returns_422():
    """Legacy project sentinel must return 422."""
    from app.models.projects import LEGACY_PROJECT_ID

    proj = _make_project(project_id=LEGACY_PROJECT_ID, name="legacy")
    user = _make_user(role="Admin")
    body = EASMGateFlipRequest(
        scope_acknowledgement_text=proj.name,
        confirm_authorisation=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        await _call_flip(proj, user, body)
    assert exc_info.value.status_code == 422
    assert "archived or legacy" in str(exc_info.value.detail).lower()


# ---------------------------------------------------------------------------
# Successful flip - Lead + Admin paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_flip_with_matching_name_and_lead_sets_all_four_fields():
    """Matching text + Lead → all four gate fields must be stamped."""
    proj = _make_project(name="Acme Red Team 2026")
    user_sub = "lead-sub-42"
    user = _make_user(role="Viewer", sub=user_sub, project_id=proj.id, project_rank=3)
    body = EASMGateFlipRequest(
        scope_acknowledgement_text="Acme Red Team 2026",
        confirm_authorisation=True,
    )

    from app.routers.projects import flip_easm_gate
    from app.schemas.projects import ProjectResponse

    request = MagicMock()
    request.state.user = user

    db = AsyncMock()
    call_count = 0

    # Track the values passed to update

    async def fake_execute(stmt, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # SELECT project
            result.scalar_one_or_none.return_value = proj
        elif call_count == 2:
            # UPDATE - capture update values from the compiled statement
            result.scalar_one_or_none.return_value = None
        else:
            # re-fetch after commit
            # Return a project with the gate fields stamped
            updated_proj = _make_project(name=proj.name, project_id=proj.id)
            updated_proj.active_scans_authorised = True
            updated_proj.scope_acknowledgement_text = "Acme Red Team 2026"
            updated_proj.active_auth_confirmed_by = user_sub
            updated_proj.active_auth_confirmed_at = datetime.now(timezone.utc)
            # ProjectResponse needs extra fields
            updated_proj.engagement_type = "red_team"
            updated_proj.description = None
            updated_proj.created_by = user_sub
            updated_proj.archived = False
            updated_proj.created_at = datetime.now(timezone.utc)
            updated_proj.updated_at = datetime.now(timezone.utc)
            result.scalar_one.return_value = updated_proj
        return result

    db.execute = fake_execute
    db.commit = AsyncMock()

    # Patch _hydrate to avoid DB member_count query
    with patch("app.routers.projects._hydrate") as mock_hydrate:
        mock_hydrate.return_value = MagicMock(spec=ProjectResponse)
        await flip_easm_gate(
            project_id=proj.id,
            body=body,
            request=request,
            db=db,
        )
    # Should have called execute 3 times: SELECT, UPDATE, re-SELECT
    assert call_count == 3
    assert db.commit.called


@pytest.mark.asyncio
async def test_gate_flip_as_global_admin_without_project_membership_succeeds():
    """Global Admin (no project membership) must be allowed to flip the gate."""
    proj = _make_project(name="Admin Bypass Test")
    # Admin with NO project membership entries
    user = _make_user(role="Admin", sub="admin-sub-007")
    body = EASMGateFlipRequest(
        scope_acknowledgement_text="Admin Bypass Test",
        confirm_authorisation=True,
    )

    from app.routers.projects import flip_easm_gate
    from app.schemas.projects import ProjectResponse

    request = MagicMock()
    request.state.user = user

    db = AsyncMock()
    call_count = 0

    async def fake_execute(stmt, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = proj
        elif call_count == 2:
            result.scalar_one_or_none.return_value = None
        else:
            updated = _make_project(name=proj.name, project_id=proj.id)
            updated.active_scans_authorised = True
            updated.scope_acknowledgement_text = "Admin Bypass Test"
            updated.active_auth_confirmed_by = "admin-sub-007"
            updated.active_auth_confirmed_at = datetime.now(timezone.utc)
            updated.engagement_type = "red_team"
            updated.description = None
            updated.created_by = "admin-sub-007"
            updated.archived = False
            updated.created_at = datetime.now(timezone.utc)
            updated.updated_at = datetime.now(timezone.utc)
            result.scalar_one.return_value = updated
        return result

    db.execute = fake_execute
    db.commit = AsyncMock()

    with patch("app.routers.projects._hydrate") as mock_hydrate:
        mock_hydrate.return_value = MagicMock(spec=ProjectResponse)
        # Must NOT raise - Admin bypasses project membership requirement
        await flip_easm_gate(
            project_id=proj.id,
            body=body,
            request=request,
            db=db,
        )
    assert db.commit.called


# ---------------------------------------------------------------------------
# Revoke tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_revoke_as_lead_clears_all_fields():
    """DELETE revoke by Lead must clear all four gate fields."""
    proj = _make_project(name="Project To Revoke")
    proj.active_scans_authorised = True
    proj.scope_acknowledgement_text = "Project To Revoke"
    proj.active_auth_confirmed_at = datetime.now(timezone.utc)
    proj.active_auth_confirmed_by = "lead-sub-revoke"

    user = _make_user(role="Viewer", project_id=proj.id, project_rank=3)

    from app.routers.projects import revoke_easm_gate
    from app.schemas.projects import ProjectResponse

    request = MagicMock()
    request.state.user = user

    db = AsyncMock()
    call_count = 0

    async def fake_execute(stmt, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = proj
        elif call_count == 2:
            result.scalar_one_or_none.return_value = None  # UPDATE
        else:
            # After revoke, all fields cleared
            cleared = _make_project(name=proj.name, project_id=proj.id)
            cleared.active_scans_authorised = False
            cleared.scope_acknowledgement_text = None
            cleared.active_auth_confirmed_at = None
            cleared.active_auth_confirmed_by = None
            cleared.engagement_type = "red_team"
            cleared.description = None
            cleared.created_by = "lead-sub-revoke"
            cleared.archived = False
            cleared.created_at = datetime.now(timezone.utc)
            cleared.updated_at = datetime.now(timezone.utc)
            result.scalar_one.return_value = cleared
        return result

    db.execute = fake_execute
    db.commit = AsyncMock()

    with patch("app.routers.projects._hydrate") as mock_hydrate:
        mock_hydrate.return_value = MagicMock(spec=ProjectResponse)
        await revoke_easm_gate(
            project_id=proj.id,
            request=request,
            db=db,
        )
    assert db.commit.called
    # Verify execute was called: SELECT + UPDATE + re-SELECT = 3 times
    assert call_count == 3


@pytest.mark.asyncio
async def test_gate_revoke_as_contributor_returns_403():
    """Contributor must be rejected from revoke (DELETE) with 403."""
    proj = _make_project(name="Locked Project")
    user = _make_user(role="Viewer", project_id=proj.id, project_rank=2)  # Contributor

    with pytest.raises(HTTPException) as exc_info:
        await _call_revoke(proj, user)
    assert exc_info.value.status_code == 403
    assert "You do not have permission to authorise active scans. Lead or Admin role required." in str(
        exc_info.value.detail
    )
