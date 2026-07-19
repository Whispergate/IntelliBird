"""UX-01 backend coverage: PATCH /api/projects/{project_id}/scope/{row_id} merged-state validation.

-01 - Wave 1 test scaffolding.

Three tests covering the merged-state invariant at projects.py:798-801:
  1. all-flags-false rejection: PATCH that would leave both intel_scope=false AND
     active_test_scope=false returns 422 with toast-friendly detail string.
  2. single-flag-toggle OK: PATCH leaving intel_scope=true (active_test_scope already false)
     returns 200.
  3. exclude-toggle independence: PATCH {"exclude": true} is accepted regardless of
     intel/active state.

Fixture: two_project_fixture (Wave-0 seed) provides project_a + jwt_a (Lead rank
on project_a - Lead satisfies Contributor+ requirement for PATCH).

Auth harness: mirrors test_prod01_cross_project_leakage._patch_auth verbatim.
"""
from __future__ import annotations

import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.integration

TEST_SIGNING_KEY = "j" * 64  # matches two_project.py fixture mint key


# ---------------------------------------------------------------------------
# Harness helpers - mirror test_prod01_cross_project_leakage._patch_auth
# ---------------------------------------------------------------------------


def _patch_auth(monkeypatch) -> None:
    """Enable AUTH_ENABLED, pin signing key, stub token_version/jti checks."""
    import app.middleware.auth as auth_mod
    from app.config import settings

    monkeypatch.setattr(settings, "AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "JWT_SIGNING_KEY", TEST_SIGNING_KEY, raising=False)

    async def _tv(_user_id: str):
        return 0

    async def _not_revoked(_jti: str) -> bool:
        return False

    monkeypatch.setattr(auth_mod, "_get_cached_token_version", _tv)
    monkeypatch.setattr(auth_mod, "_is_jti_revoked", _not_revoked)


async def _client():
    from app.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Scope row seed helpers
# ---------------------------------------------------------------------------


async def _seed_scope_row(
    db_session,
    project_id: uuid.UUID,
    *,
    intel_scope: bool = True,
    active_test_scope: bool = False,
    exclude: bool = False,
) -> uuid.UUID:
    """Insert a domain scope row with the given flag state. Returns the row id."""
    row_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO project_scope_rows "
            "(id, project_id, scope_type, value, intel_scope, active_test_scope, exclude) "
            "VALUES (:rid, :pid, 'domain', :val, :intel, :active, :excl)"
        ),
        {
            "rid": row_id,
            "pid": project_id,
            "val": f"test-{row_id}.example.com",
            "intel": intel_scope,
            "active": active_test_scope,
            "excl": exclude,
        },
    )
    await db_session.commit()
    return row_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_rejects_both_flags_false(
    two_project_fixture, db_session, monkeypatch
):
    """PATCH that would leave both intel_scope=false AND active_test_scope=false
    must return 422 with a toast-friendly detail string.

    Setup: seed a row with intel_scope=true, active_test_scope=false.
    Patch: {"intel_scope": False} - merged state would be both false.
    Expect: 422, detail contains "at least intel or active test".

    Backend enforcement point: projects.py:798-801 (after field-by-field apply,
    before commit). This is the merged-state guard that Pydantic's model_validator
    on ScopeRowUpdate cannot catch (it only sees the patch body, not current row).
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_a_id = fx.project_a.id

    # Seed a row: intel_scope=True, active_test_scope=False. Patching
    # intel_scope → False would leave both flags false.
    row_id = await _seed_scope_row(
        db_session,
        project_a_id,
        intel_scope=True,
        active_test_scope=False,
    )

    async with await _client() as c:
        r = await c.patch(
            f"/api/projects/{project_a_id}/scope/{row_id}",
            json={"intel_scope": False},
            headers=_bearer(fx.jwt_a),
        )

    assert r.status_code == 422, (
        f"Expected 422 for both-flags-false PATCH, got {r.status_code}. Body: {r.text}"
    )
    detail = r.json().get("detail", "")
    assert "at least intel or active test" in detail.lower(), (
        f"422 detail must contain 'at least intel or active test' for toast surfacing. "
        f"Got: {detail!r}"
    )


@pytest.mark.asyncio
async def test_patch_single_flag_succeeds(
    two_project_fixture, db_session, monkeypatch
):
    """PATCH that leaves intel_scope=true (while setting active_test_scope=false)
    must return 200 - merged state is valid (intel_scope covers the invariant).

    Setup: seed a row with intel_scope=true, active_test_scope=true.
    Patch: {"active_test_scope": False} - merged state: intel_scope=true, active=false.
    Expect: 200, response body shows intel_scope=true.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_a_id = fx.project_a.id

    row_id = await _seed_scope_row(
        db_session,
        project_a_id,
        intel_scope=True,
        active_test_scope=True,
    )

    async with await _client() as c:
        r = await c.patch(
            f"/api/projects/{project_a_id}/scope/{row_id}",
            json={"active_test_scope": False},
            headers=_bearer(fx.jwt_a),
        )

    assert r.status_code == 200, (
        f"Expected 200 for valid single-flag-toggle PATCH, got {r.status_code}. Body: {r.text}"
    )
    body = r.json()
    assert body["intel_scope"] is True, (
        f"intel_scope must remain True after patching only active_test_scope. Got: {body}"
    )
    assert body["active_test_scope"] is False, (
        f"active_test_scope must be False after patch. Got: {body}"
    )


@pytest.mark.asyncio
async def test_patch_exclude_toggle_independent(
    two_project_fixture, db_session, monkeypatch
):
    """PATCH {"exclude": True} on a valid row must return 200 regardless of intel/active state.

    The `exclude` flag is a filter directive (subtract from include matches), not
    part of the at-least-one-of invariant. Toggling it does NOT affect intel_scope
    or active_test_scope, so the merged-state guard (projects.py:798) always passes
    as long as the row has at least one of intel/active true.

    Setup: seed a row with intel_scope=true, active_test_scope=false, exclude=false.
    Patch: {"exclude": True}.
    Expect: 200, exclude=True in response body. intel_scope + active_test_scope unchanged.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_a_id = fx.project_a.id

    row_id = await _seed_scope_row(
        db_session,
        project_a_id,
        intel_scope=True,
        active_test_scope=False,
        exclude=False,
    )

    async with await _client() as c:
        r = await c.patch(
            f"/api/projects/{project_a_id}/scope/{row_id}",
            json={"exclude": True},
            headers=_bearer(fx.jwt_a),
        )

    assert r.status_code == 200, (
        f"Expected 200 for exclude-toggle PATCH, got {r.status_code}. Body: {r.text}"
    )
    body = r.json()
    assert body["exclude"] is True, (
        f"exclude must be True after patch. Got: {body}"
    )
    assert body["intel_scope"] is True, (
        f"intel_scope must remain True after exclude-only patch. Got: {body}"
    )
    assert body["active_test_scope"] is False, (
        f"active_test_scope must remain False after exclude-only patch. Got: {body}"
    )
