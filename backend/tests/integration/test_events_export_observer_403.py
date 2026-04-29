"""Defense-in-depth test: export endpoint returns 403 for Observer JWT.

Phase 20 Plan 04 (UX-02): The frontend hides the Export button for Observers
(UX polish). The backend enforces the gate independently — a direct API call
with an Observer JWT must receive 403 regardless of frontend state.

Endpoint: POST /api/projects/{project_id}/export?format=stix
Min role gate: Contributor+ (require_project_membership(ProjectRole.Contributor))
  - Observer (rank 1) → 403
  - Contributor (rank 2) → 200 (positive control)

Auth pattern mirrors test_prod01_cross_project_leakage: real JWTs minted via
mint_access_token_with_pm + AUTH_ENABLED patched true + stub token_version/jti.
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

from app.security.jwt import mint_access_token_with_pm, PROJECT_ROLE_RANK

pytestmark = pytest.mark.integration

TEST_SIGNING_KEY = "j" * 64  # matches two_project.py fixture mint key


# ---------------------------------------------------------------------------
# Harness helpers — mirror test_prod01_cross_project_leakage pattern
# ---------------------------------------------------------------------------


def _patch_auth(monkeypatch) -> None:
    """Enable AUTH_ENABLED, pin signing key, stub token_version/jti checks."""
    import app.middleware.auth as auth_mod
    from app.config import settings

    monkeypatch.setattr(settings, "AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "JWT_SIGNING_KEY", TEST_SIGNING_KEY, raising=False)

    async def _tv(_user_id: str):
        return 0  # matches fixture-minted token_version

    async def _not_revoked(_jti: str) -> bool:
        return False

    monkeypatch.setattr(auth_mod, "_get_cached_token_version", _tv)
    monkeypatch.setattr(auth_mod, "_is_jti_revoked", _not_revoked)


async def _client():
    """Async httpx client wrapping the real FastAPI app."""
    from app.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _mint_token(project_id: uuid.UUID, role: str) -> str:
    """Mint an access token for user with given project role."""
    user_id = str(uuid.uuid4())
    pm = [[str(project_id), PROJECT_ROLE_RANK[role]]]
    token, _ = mint_access_token_with_pm(
        user_id, "Analyst", ["red", "blue"], 0, TEST_SIGNING_KEY, pm, False,
    )
    return token


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_observer_export_returns_403(two_project_fixture, monkeypatch):
    """Observer JWT → 403 on export endpoint (backend defense-in-depth).

    The frontend hides the Export button for Observers; this test asserts the
    backend gate independently — a direct API call must still return 403.

    Min role for export is Contributor (require_project_membership(Contributor)).
    Observer rank=1 < Contributor rank=2 → 403.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture

    jwt_observer = _mint_token(fx.project_a.id, "Observer")

    async with await _client() as c:
        r = await c.post(
            f"/api/projects/{fx.project_a.id}/export",
            headers=_bearer(jwt_observer),
            params={"format": "stix"},
        )

    assert r.status_code == 403, (
        f"Expected 403 for Observer JWT on export endpoint, got {r.status_code}: {r.text}"
    )


@pytest.mark.asyncio
async def test_contributor_export_succeeds(two_project_fixture, db_session, monkeypatch):
    """Contributor JWT → 200 on export endpoint (positive control).

    Proves the gate discriminates: Observer → 403, Contributor → 200.
    Seeds a scope row so the project has something to export (otherwise the
    export may return 200 with an empty body, which is still a success).
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture

    # Seed a scope row so the project has scope (not strictly required for 200
    # but ensures the export path runs fully and is not vacuous).
    await db_session.execute(
        text(
            "INSERT INTO project_scope_rows "
            "(id, project_id, scope_type, value, intel_scope, active_test_scope, exclude) "
            "VALUES (gen_random_uuid(), :pid, 'keyword', 'evt', true, false, false)"
        ),
        {"pid": fx.project_a.id},
    )
    await db_session.commit()

    jwt_contributor = _mint_token(fx.project_a.id, "Contributor")

    async with await _client() as c:
        r = await c.post(
            f"/api/projects/{fx.project_a.id}/export",
            headers=_bearer(jwt_contributor),
            params={"format": "stix"},
        )

    # Accept 200 (export ready) or 413 (event cap exceeded — test data may
    # exceed cap in some setups). Both confirm the Contributor gate passed.
    # 403 would mean the gate incorrectly rejected a Contributor.
    assert r.status_code in (200, 413), (
        f"Expected 200 or 413 for Contributor JWT on export endpoint, got {r.status_code}: {r.text}"
    )
