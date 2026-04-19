"""POST /api/auth/* + GET /api/auth/me — AUTH-01, AUTH-03.

Endpoints:
  POST /api/auth/login              local-credentials login
  POST /api/auth/refresh            rotate access + refresh (PITFALL 4 reuse detection)
  POST /api/auth/logout             revoke current JTIs
  GET  /api/auth/me                 current user summary
  POST /api/auth/change-password    rotate password + bump token_version
  GET  /api/auth/oidc/login         redirect to Authentik (added below)
  GET  /api/auth/oidc/callback      Authentik callback (added below)

Response shape conforms to UI-SPEC.md:
  user: { id, username, role, dashboard_roles, must_change_password }

Cookie: refresh_token, httpOnly, Secure (when X-Forwarded-Proto==https), SameSite=Lax, Path=/.
"""
from __future__ import annotations

import hashlib
import base64
import secrets
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

import jwt as pyjwt
import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.middleware.auth import require_auth
from app.models.users import User
from app.security.jwt import (
    ACCESS_TOKEN_TTL_SECONDS,
    REFRESH_TOKEN_TTL_SECONDS,
    AuthUser,
    decode_token,
    mint_access_token,
    mint_refresh_token,
)
from app.security.lockout import (
    FAILS_THRESHOLD,
    clear_lockout,
    is_locked,
    record_failure,
)
from app.security.passwords import (
    hash_password,
    verify_and_maybe_rehash,
    verify_dummy,
)
from app.security.oidc import (
    build_oidc_client,
    fetch_server_metadata,
    map_groups_to_role,
    verify_id_token,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"
OIDC_STATE_COOKIE = "oidc_state"
OIDC_VERIFIER_COOKIE = "oidc_verifier"
OIDC_NONCE_COOKIE = "oidc_nonce"
OIDC_COOKIE_TTL = 300  # 5 minutes — state round-trip must complete quickly


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class UserPublic(BaseModel):
    id: str
    username: str
    role: str
    dashboard_roles: list[str]
    must_change_password: bool


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=512)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_TTL_SECONDS
    user: UserPublic


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=12, max_length=512)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _redis_client():
    import redis.asyncio as aioredis
    return aioredis.from_url(settings.REDIS_URL)


def _cookie_secure(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    return forwarded_proto == "https"


def _set_refresh_cookie(response: Response, token: str, request: Request) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=REFRESH_TOKEN_TTL_SECONDS,
        path="/",
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
    )


def _build_user_public(u: User) -> UserPublic:
    return UserPublic(
        id=str(u.id),
        username=u.username,
        role=u.role,
        dashboard_roles=list(u.dashboard_roles or []),
        must_change_password=bool(u.must_change_password),
    )


async def _issue_tokens_and_cookie(
    u: User, request: Request, response: Response,
) -> TokenResponse:
    access, _ = mint_access_token(
        str(u.id), u.role, list(u.dashboard_roles or []), u.token_version,
        settings.JWT_SIGNING_KEY,
    )
    refresh, _ = mint_refresh_token(
        str(u.id), u.role, list(u.dashboard_roles or []), u.token_version,
        settings.JWT_SIGNING_KEY,
    )
    _set_refresh_cookie(response, refresh, request)
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user=_build_user_public(u),
    )


# ---------------------------------------------------------------------------
# /login
# ---------------------------------------------------------------------------

@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> TokenResponse:
    redis = await _redis_client()
    try:
        locked, retry_after = await is_locked(redis, body.username)
        if locked:
            response.headers["Retry-After"] = str(retry_after)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="account_locked",
                headers={"Retry-After": str(retry_after)},
            )

        user = (await db.execute(
            select(User).where(User.username == body.username)
        )).scalar_one_or_none()

        if user is None:
            # PITFALL 7 — equalise timing for enumeration protection.
            verify_dummy()
            await record_failure(redis, body.username)
            raise HTTPException(status_code=401, detail="invalid_credentials")

        if not user.enabled:
            raise HTTPException(status_code=403, detail="user_disabled")

        if user.password_hash is None:
            # OIDC-only user attempting local login
            await record_failure(redis, body.username)
            raise HTTPException(status_code=401, detail="invalid_credentials")

        valid, new_hash = verify_and_maybe_rehash(body.password, user.password_hash)
        if not valid:
            await record_failure(redis, body.username)
            raise HTTPException(status_code=401, detail="invalid_credentials")

        if new_hash is not None:
            user.password_hash = new_hash
        user.last_login_at = datetime.now(timezone.utc)
        await db.commit()
        await clear_lockout(redis, body.username)

        log.info("auth_login_ok", user_id=str(user.id), username=user.username)
        return await _issue_tokens_and_cookie(user, request, response)
    finally:
        await redis.aclose()


# ---------------------------------------------------------------------------
# /refresh — rotation + reuse detection (PITFALL 4)
# ---------------------------------------------------------------------------

@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    db: AsyncSession = Depends(get_session),
) -> TokenResponse:
    if not refresh_token:
        raise HTTPException(status_code=401, detail="invalid_token")

    try:
        claims = decode_token(refresh_token, settings.JWT_SIGNING_KEY)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="expired_token")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid_token")

    if claims.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="invalid_token")

    redis = await _redis_client()
    try:
        # Reuse detection BEFORE rotation (PITFALL 4)
        old_jti = claims["jti"]
        already_revoked = await redis.exists(f"jwt:revoked:{old_jti}")
        if already_revoked:
            log.error(
                "auth_refresh_reuse_detected",
                user_id=claims.get("sub"),
                jti=old_jti,
                remote_addr=request.client.host if request.client else None,
            )
            # Bump token_version to invalidate ALL outstanding tokens for this user
            user_id = uuid.UUID(claims["sub"])
            await db.execute(
                User.__table__.update()
                .where(User.id == user_id)
                .values(token_version=User.token_version + 1)
            )
            await db.commit()
            response.headers["X-Session-Revoked"] = "reuse_detected"
            raise HTTPException(
                status_code=401,
                detail="revoked_token",
                headers={"X-Session-Revoked": "reuse_detected"},
            )

        # Revoke the old refresh JTI FIRST (before minting new — PITFALL 4 ordering)
        await redis.set(
            f"jwt:revoked:{old_jti}",
            "1",
            ex=REFRESH_TOKEN_TTL_SECONDS,
        )

        # token_version check against DB
        user = (await db.execute(
            select(User).where(User.id == uuid.UUID(claims["sub"]))
        )).scalar_one_or_none()
        if user is None or not user.enabled:
            raise HTTPException(status_code=401, detail="invalid_token")
        if int(claims["token_version"]) < user.token_version:
            raise HTTPException(status_code=401, detail="revoked_token")

        return await _issue_tokens_and_cookie(user, request, response)
    finally:
        await redis.aclose()


# ---------------------------------------------------------------------------
# /logout
# ---------------------------------------------------------------------------

@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    user: AuthUser = Depends(require_auth),
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> Response:
    redis = await _redis_client()
    try:
        # Revoke access JTI (15-min TTL)
        await redis.set(
            f"jwt:revoked:{user.jti}", "1",
            ex=ACCESS_TOKEN_TTL_SECONDS,
        )
        # Revoke refresh JTI if cookie present
        if refresh_token:
            try:
                r_claims = decode_token(refresh_token, settings.JWT_SIGNING_KEY)
                if r_claims.get("type") == "refresh":
                    await redis.set(
                        f"jwt:revoked:{r_claims['jti']}",
                        "1",
                        ex=REFRESH_TOKEN_TTL_SECONDS,
                    )
            except pyjwt.InvalidTokenError:
                pass  # bad refresh cookie — nothing to revoke
    finally:
        await redis.aclose()

    response.delete_cookie(REFRESH_COOKIE_NAME, path="/")
    log.info("auth_logout", user_id=user.id, jti=user.jti)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# /me
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserPublic)
async def me(
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> UserPublic:
    row = (await db.execute(
        select(User).where(User.id == uuid.UUID(user.id))
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    return _build_user_public(row)


# ---------------------------------------------------------------------------
# /change-password
# ---------------------------------------------------------------------------

@router.post("/change-password", response_model=TokenResponse)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    user: AuthUser = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
) -> TokenResponse:
    row = (await db.execute(
        select(User).where(User.id == uuid.UUID(user.id))
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    if row.password_hash is None:
        raise HTTPException(status_code=400, detail="oidc_only_user")

    valid, _ = verify_and_maybe_rehash(body.current_password, row.password_hash)
    if not valid:
        raise HTTPException(status_code=401, detail="invalid_credentials")
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="new_password_same_as_current")

    row.password_hash = hash_password(body.new_password)
    row.must_change_password = False
    row.token_version = (row.token_version or 0) + 1  # bulk-invalidate all outstanding tokens
    await db.commit()

    log.info("auth_password_changed", user_id=str(row.id))
    return await _issue_tokens_and_cookie(row, request, response)


# ---------------------------------------------------------------------------
# OIDC — Authentik authorization code flow with PKCE
# ---------------------------------------------------------------------------

def _pkce_challenge() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


@router.get("/oidc/login")
async def oidc_login(request: Request) -> Response:
    if not settings.SSO_ISSUER_URL or not settings.SSO_CLIENT_ID:
        raise HTTPException(status_code=404, detail="oidc_not_configured")

    metadata = await fetch_server_metadata(settings.SSO_ISSUER_URL)

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_challenge()

    redirect_uri = f"{settings.DASHBOARD_URL}/api/auth/oidc/callback"
    params = {
        "client_id": settings.SSO_CLIENT_ID,
        "response_type": "code",
        "scope": f"openid profile email {settings.SSO_GROUPS_CLAIM}",
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "nonce": nonce,
    }
    authorization_url = f"{metadata['authorization_endpoint']}?{urlencode(params)}"

    response = Response(status_code=302)
    response.headers["Location"] = authorization_url
    for cookie_name, value in (
        (OIDC_STATE_COOKIE, state),
        (OIDC_VERIFIER_COOKIE, verifier),
        (OIDC_NONCE_COOKIE, nonce),
    ):
        response.set_cookie(
            key=cookie_name,
            value=value,
            max_age=OIDC_COOKIE_TTL,
            path="/",
            httponly=True,
            secure=_cookie_secure(request),
            samesite="lax",
        )
    return response


@router.get("/oidc/callback")
async def oidc_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    oidc_state: str | None = Cookie(default=None, alias=OIDC_STATE_COOKIE),
    oidc_verifier: str | None = Cookie(default=None, alias=OIDC_VERIFIER_COOKIE),
    oidc_nonce: str | None = Cookie(default=None, alias=OIDC_NONCE_COOKIE),
    db: AsyncSession = Depends(get_session),
) -> Response:
    if not settings.SSO_ISSUER_URL:
        raise HTTPException(status_code=404, detail="oidc_not_configured")
    if not code or not state:
        raise HTTPException(status_code=400, detail="missing_code_or_state")
    if state != oidc_state:
        raise HTTPException(status_code=400, detail="invalid_state")
    if oidc_verifier is None or oidc_nonce is None:
        raise HTTPException(status_code=400, detail="missing_pkce_cookies")

    metadata = await fetch_server_metadata(settings.SSO_ISSUER_URL)

    client = await build_oidc_client()
    if client is None:
        raise HTTPException(status_code=500, detail="oidc_client_unavailable")
    try:
        token_resp = await client.fetch_token(
            metadata["token_endpoint"],
            code=code,
            code_verifier=oidc_verifier,
            redirect_uri=f"{settings.DASHBOARD_URL}/api/auth/oidc/callback",
        )
    finally:
        await client.aclose()

    id_token: str = token_resp["id_token"]
    claims = await verify_id_token(id_token, metadata["jwks_uri"])
    if claims.get("nonce") != oidc_nonce:
        raise HTTPException(status_code=400, detail="invalid_nonce")

    sub: str = claims["sub"]
    groups: list[str] = list(claims.get(settings.SSO_GROUPS_CLAIM, []) or [])
    role = map_groups_to_role(
        groups,
        admin_groups=settings.SSO_ADMIN_GROUPS,
        analyst_groups=settings.SSO_ANALYST_GROUPS,
        viewer_groups=settings.SSO_VIEWER_GROUPS,
    )
    username = claims.get("preferred_username") or claims.get("email") or f"authentik:{sub[:8]}"

    # Upsert user by oidc_sub
    existing = (await db.execute(
        select(User).where(User.oidc_sub == sub)
    )).scalar_one_or_none()

    if existing is None:
        dashboard_roles = ["red", "blue"] if role == "Admin" else []
        u = User(
            username=username,
            password_hash=None,
            oidc_sub=sub,
            role=role,
            dashboard_roles=dashboard_roles,
            enabled=True,
            must_change_password=False,
            token_version=0,
            last_login_at=datetime.now(timezone.utc),
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
    else:
        existing.last_login_at = datetime.now(timezone.utc)
        # Role may change when group assignments change in Authentik
        existing.role = role
        if role == "Admin" and not existing.dashboard_roles:
            existing.dashboard_roles = ["red", "blue"]
        await db.commit()
        u = existing

    # Choose landing URL based on dashboard_roles
    landing_dashboard = "/red" if "red" in (u.dashboard_roles or []) else "/blue"
    if not u.dashboard_roles:
        landing_dashboard = "/"

    response = Response(status_code=302)
    response.headers["Location"] = landing_dashboard
    # Issue tokens + refresh cookie (same helper)
    await _issue_tokens_and_cookie(u, request, response)
    # Clear PKCE cookies
    for c in (OIDC_STATE_COOKIE, OIDC_VERIFIER_COOKIE, OIDC_NONCE_COOKIE):
        response.delete_cookie(c, path="/")

    log.info(
        "auth_oidc_callback_ok",
        user_id=str(u.id),
        role=role,
        new_user=existing is None,
    )
    return response
