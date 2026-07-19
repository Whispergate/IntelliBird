"""Role gate Depends unit tests - AUTH-02."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@h/d")
os.environ.setdefault("SECRET_KEY", "b" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "a" * 64)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

from app.middleware.auth import require_admin, require_analyst_or_above, require_auth  # noqa: E402
from app.security.jwt import AuthUser  # noqa: E402


def _make_request(user: AuthUser | None) -> Request:
    scope = {"type": "http", "path": "/protected", "headers": []}
    req = Request(scope)
    if user is not None:
        req.state.user = user
    return req


def test_require_auth_no_user_raises_401():
    req = _make_request(None)
    with pytest.raises(HTTPException) as exc:
        require_auth(req)
    assert exc.value.status_code == 401
    assert exc.value.detail == "invalid_token"


def test_require_auth_returns_user():
    u = AuthUser(id="x", role="Admin", dashboard_roles=["red"], jti="j", token_version=0)
    req = _make_request(u)
    assert require_auth(req) is u


def test_require_admin_rejects_analyst():
    u = AuthUser(id="x", role="Analyst", dashboard_roles=["red"], jti="j", token_version=0)
    with pytest.raises(HTTPException) as exc:
        require_admin(u)
    assert exc.value.status_code == 403
    assert exc.value.detail == "insufficient_role"


def test_require_admin_rejects_viewer():
    u = AuthUser(id="x", role="Viewer", dashboard_roles=[], jti="j", token_version=0)
    with pytest.raises(HTTPException) as exc:
        require_admin(u)
    assert exc.value.status_code == 403


def test_require_admin_accepts_admin():
    u = AuthUser(id="x", role="Admin", dashboard_roles=["red"], jti="j", token_version=0)
    assert require_admin(u) is u


def test_require_analyst_or_above_rejects_viewer():
    u = AuthUser(id="x", role="Viewer", dashboard_roles=[], jti="j", token_version=0)
    with pytest.raises(HTTPException) as exc:
        require_analyst_or_above(u)
    assert exc.value.status_code == 403


def test_require_analyst_or_above_accepts_analyst():
    u = AuthUser(id="x", role="Analyst", dashboard_roles=["red"], jti="j", token_version=0)
    assert require_analyst_or_above(u) is u


def test_require_analyst_or_above_accepts_admin():
    u = AuthUser(id="x", role="Admin", dashboard_roles=["red", "blue"], jti="j", token_version=0)
    assert require_analyst_or_above(u) is u
