"""AuthMiddleware + role gate dependencies — AUTH-02, AUTH-03.

Replaces the stub. Validation chain per CONTEXT.md:
  1. Bearer token extracted from Authorization header.
  2. PyJWT signature + exp validated via app.security.jwt.decode_token.
  3. claim 'type' must be 'access' (refresh tokens are not valid on protected endpoints).
  4. claim 'token_version' checked against users.token_version (30s in-memory TTL cache).
  5. Redis jwt:revoked:{jti} checked — FAIL-CLOSED: Redis connection error returns 503.
  6. request.state.user populated with AuthUser dataclass.

EXEMPT_PATHS (pre-auth surface — must not require a token):
  /healthz                       Docker healthcheck
  /api/system/status             NoAuthBanner fetch (must render pre-login)
  /api/admin/rekey-credentials pre-auth setup-token-gated recovery
  /api/admin/setup               pre-auth SETUP_TOKEN-gated first-admin bootstrap
  /api/auth/login                local credentials login
  /api/auth/refresh              refresh token rotation (cookie-authenticated, not bearer)
  /api/auth/oidc/login           redirect to Authentik
  /api/auth/oidc/callback        Authentik redirect target

TAXII 2.1 exemption:
  /taxii2 (all sub-paths, checked via startswith) — TAXII 2.1 outbound server uses its
  own partner-key authentication (require_taxii_client Depends), not JWT bearer tokens.
  The startswith check is used (not a frozenset entry) to cover all TAXII sub-paths.

ASGI order (lock from — preserved):
  outermost -> innermost = RequestLogMiddleware -> AuthMiddleware -> CORSMiddleware -> route
"""
from __future__ import annotations

import time
import uuid
from typing import Any

import jwt as pyjwt
import structlog
from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings
from app.database import async_session_factory
from app.models.users import User
from app.security.jwt import AuthUser, decode_token

log = structlog.get_logger(__name__)

EXEMPT_PATHS: frozenset[str] = frozenset({
    "/healthz",
    "/api/system/status",
    "/api/system/setup-status",
    "/api/admin/rekey-credentials",
    "/api/admin/setup",
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/auth/oidc/login",
    "/api/auth/oidc/callback",
})

# ---------------------------------------------------------------------------
# token_version cache — 30-second in-memory TTL per worker (CONTEXT.md;
# accept the multi-worker consistency gap per PITFALL 5)
# ---------------------------------------------------------------------------

_TOKEN_VERSION_CACHE: dict[str, tuple[int, float]] = {}
_TOKEN_VERSION_TTL_SECONDS: float = 30.0


async def _get_cached_token_version(user_id: str) -> int | None:
    now = time.monotonic()
    cached = _TOKEN_VERSION_CACHE.get(user_id)
    if cached is not None and (now - cached[1]) < _TOKEN_VERSION_TTL_SECONDS:
        return cached[0]
    try:
        async with async_session_factory() as session:
            row = (await session.execute(
                select(User.token_version).where(User.id == uuid.UUID(user_id))
            )).scalar_one_or_none()
    except Exception:
        return None
    if row is None:
        return None
    _TOKEN_VERSION_CACHE[user_id] = (int(row), now)
    return int(row)


# ---------------------------------------------------------------------------
# Redis blocklist — fail-closed 503 on connection error
# ---------------------------------------------------------------------------

async def _is_jti_revoked(jti: str) -> bool:
    """Raises RuntimeError('auth_infra_down') on Redis failure — caller translates to 503."""
    import redis.asyncio as aioredis
    try:
        client = aioredis.from_url(settings.REDIS_URL)
        try:
            exists = await client.exists(f"jwt:revoked:{jti}")
        finally:
            await client.aclose()
    except Exception as exc:
        raise RuntimeError("auth_infra_down") from exc
    return bool(exists)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in EXEMPT_PATHS or request.url.path.startswith("/taxii2"):
            return await call_next(request)
        if not settings.AUTH_ENABLED:
            # AUTH_ENABLED=false dev mode: inject a stub Admin user so + routers
            # (which depend on require_auth / require_analyst_or_above / require_admin)
            # function without a real JWT. The NoAuthBanner surface already warns the
            # operator that auth is disabled. Loopback-bind + docs/ops runbook are the
            # compensating controls until PROD-07 removes the loopback prefix.
            request.state.user = AuthUser(
                id="dev-admin",
                role="Admin",
                dashboard_roles=["red", "blue"],
                jti="dev-stub",
                token_version=0,
                project_memberships={},
                pm_truncated=False,
            )
            return await call_next(request)

        # 1. Extract bearer token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse({"detail": "invalid_token"}, status_code=401)
        token = auth_header[len("Bearer "):]

        # 2. Signature + exp validation
        try:
            claims = decode_token(token, settings.JWT_SIGNING_KEY)
        except pyjwt.ExpiredSignatureError:
            return JSONResponse(
                {"detail": "expired_token"},
                status_code=401,
                headers={"X-Refresh-Required": "true"},
            )
        except pyjwt.InvalidTokenError:
            return JSONResponse({"detail": "invalid_token"}, status_code=401)

        # 3. type check — only access tokens reach protected endpoints
        if claims.get("type") != "access":
            return JSONResponse({"detail": "invalid_token"}, status_code=401)

        # 4. token_version check (30s in-memory TTL cache)
        current_tv = await _get_cached_token_version(claims["sub"])
        if current_tv is None or claims["token_version"] < current_tv:
            return JSONResponse({"detail": "revoked_token"}, status_code=401)

        # 5. Redis JTI blocklist — fail-closed 503 on connection error (PITFALL 3)
        try:
            revoked = await _is_jti_revoked(claims["jti"])
        except RuntimeError:
            log.error("auth_infra_down", path=request.url.path)
            return JSONResponse({"detail": "auth_infra_down"}, status_code=503)
        if revoked:
            return JSONResponse({"detail": "revoked_token"}, status_code=401)

        # 6. Populate request.state.user (includes project_memberships
        #    pm_truncated — claim keys default to [] and False for tokens minted
        # legacy.)
        # PROD-03: role MUST derive from JWT claim only; never read X-Dashboard-Role from the request.
        pm_raw = claims.get("pm", [])
        project_memberships: dict[str, int] = {}
        if isinstance(pm_raw, list):
            for entry in pm_raw:
                if isinstance(entry, list) and len(entry) == 2:
                    pid_str, rank_int = entry
                    if isinstance(pid_str, str) and isinstance(rank_int, int):
                        project_memberships[pid_str] = rank_int
        request.state.user = AuthUser(
            id=claims["sub"],
            role=claims["role"],
            dashboard_roles=list(claims.get("dashboard_roles", [])),
            jti=claims["jti"],
            token_version=int(claims["token_version"]),
            project_memberships=project_memberships,
            pm_truncated=bool(claims.get("pm_truncated", False)),
        )
        return await call_next(request)


# ---------------------------------------------------------------------------
# FastAPI dependencies — role gates
# ---------------------------------------------------------------------------

def require_auth(request: Request) -> AuthUser:
    """Return request.state.user or raise 401."""
    user: Any = getattr(request.state, "user", None)
    if not isinstance(user, AuthUser):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token")
    return user


def require_admin(user: AuthUser = Depends(require_auth)) -> AuthUser:
    if user.role != "Admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient_role")
    return user


def require_analyst_or_above(user: AuthUser = Depends(require_auth)) -> AuthUser:
    if user.role == "Viewer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient_role")
    return user
