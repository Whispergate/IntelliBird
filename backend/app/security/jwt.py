"""JWT encode/decode helpers — AUTH-03.

HS256 signing using settings.JWT_SIGNING_KEY. Token TTLs per CONTEXT.md:
  access  = 15 minutes  (900s)
  refresh = 7 days      (604800s)

Claim shape (access + refresh share structure except 'type'):
  { "sub": "<user UUID>", "role": "Admin"|"Analyst"|"Viewer",
    "dashboard_roles": ["red","blue"], "jti": "<UUID>",
    "iat": <unix>, "exp": <unix>, "type": "access"|"refresh",
    "token_version": <int> }

No username in claims — frontend fetches display info via GET /api/auth/me.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal

import jwt as pyjwt

ACCESS_TOKEN_TTL_SECONDS: int = 900
REFRESH_TOKEN_TTL_SECONDS: int = 604800
ALGORITHM: str = "HS256"

TokenType = Literal["access", "refresh"]


@dataclass(frozen=True)
class AuthUser:
    """Populated on request.state.user by AuthMiddleware after successful claim verify."""

    id: str
    role: str
    dashboard_roles: list[str]
    jti: str
    token_version: int


def _mint(
    user_id: str,
    role: str,
    dashboard_roles: list[str],
    token_version: int,
    signing_key: str,
    token_type: TokenType,
    ttl_seconds: int,
) -> tuple[str, str]:
    """Return (encoded_token, jti). Caller stores jti for potential blocklisting."""
    now = int(time.time())
    jti = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "dashboard_roles": list(dashboard_roles),
        "jti": jti,
        "iat": now,
        "exp": now + ttl_seconds,
        "type": token_type,
        "token_version": token_version,
    }
    return pyjwt.encode(payload, signing_key, algorithm=ALGORITHM), jti


def mint_access_token(
    user_id: str,
    role: str,
    dashboard_roles: list[str],
    token_version: int,
    signing_key: str,
) -> tuple[str, str]:
    """Return (access_token, jti). 15-minute TTL."""
    return _mint(
        user_id,
        role,
        dashboard_roles,
        token_version,
        signing_key,
        "access",
        ACCESS_TOKEN_TTL_SECONDS,
    )


def mint_refresh_token(
    user_id: str,
    role: str,
    dashboard_roles: list[str],
    token_version: int,
    signing_key: str,
) -> tuple[str, str]:
    """Return (refresh_token, jti). 7-day TTL."""
    return _mint(
        user_id,
        role,
        dashboard_roles,
        token_version,
        signing_key,
        "refresh",
        REFRESH_TOKEN_TTL_SECONDS,
    )


def decode_token(token: str, signing_key: str) -> dict[str, Any]:
    """Decode + verify signature + require canonical claims.

    Raises:
      pyjwt.ExpiredSignatureError — exp in the past.
      pyjwt.InvalidTokenError — signature failure, missing required claim, bad format.
    """
    return pyjwt.decode(
        token,
        signing_key,
        algorithms=[ALGORITHM],
        options={"require": ["exp", "sub", "jti", "type", "iat", "role", "token_version"]},
    )
