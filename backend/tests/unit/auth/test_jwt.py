"""JWT encode/decode unit tests - AUTH-03."""
from __future__ import annotations

import time

import jwt as pyjwt
import pytest

from app.security.jwt import (
    ACCESS_TOKEN_TTL_SECONDS,
    REFRESH_TOKEN_TTL_SECONDS,
    AuthUser,
    decode_token,
    mint_access_token,
    mint_refresh_token,
)

TEST_KEY = "a" * 32 + "b" * 32
USER_ID = "00000000-0000-0000-0000-000000000001"


def test_access_token_has_15min_ttl():
    token, _jti = mint_access_token(USER_ID, "Admin", ["red", "blue"], 0, TEST_KEY)
    claims = decode_token(token, TEST_KEY)
    assert claims["exp"] - claims["iat"] == ACCESS_TOKEN_TTL_SECONDS == 900


def test_refresh_token_has_7day_ttl():
    token, _jti = mint_refresh_token(USER_ID, "Admin", ["red", "blue"], 0, TEST_KEY)
    claims = decode_token(token, TEST_KEY)
    assert claims["exp"] - claims["iat"] == REFRESH_TOKEN_TTL_SECONDS == 604800


def test_claim_shape_access():
    token, jti = mint_access_token(USER_ID, "Analyst", ["red"], 3, TEST_KEY)
    claims = decode_token(token, TEST_KEY)
    assert claims["sub"] == USER_ID
    assert claims["role"] == "Analyst"
    assert claims["dashboard_roles"] == ["red"]
    assert claims["jti"] == jti
    assert claims["type"] == "access"
    assert claims["token_version"] == 3


def test_claim_shape_refresh_type():
    token, _ = mint_refresh_token(USER_ID, "Viewer", [], 0, TEST_KEY)
    claims = decode_token(token, TEST_KEY)
    assert claims["type"] == "refresh"


def test_unique_jti_per_mint():
    _, jti1 = mint_access_token(USER_ID, "Admin", ["red"], 0, TEST_KEY)
    _, jti2 = mint_access_token(USER_ID, "Admin", ["red"], 0, TEST_KEY)
    assert jti1 != jti2


def test_expired_token_raises():
    # Mint a token directly with exp already in the past (PyJWT validates against real time.time())
    now = int(time.time())
    expired_payload = {
        "sub": USER_ID,
        "role": "Admin",
        "dashboard_roles": ["red"],
        "jti": "expired-jti",
        "iat": now - 1000,
        "exp": now - 10,  # already expired
        "type": "access",
        "token_version": 0,
    }
    expired_token = pyjwt.encode(expired_payload, TEST_KEY, algorithm="HS256")
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_token(expired_token, TEST_KEY)


def test_tampered_signature_raises():
    token, _ = mint_access_token(USER_ID, "Admin", ["red"], 0, TEST_KEY)
    tampered = token[:-4] + "AAAA"
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_token(tampered, TEST_KEY)


def test_wrong_key_raises():
    token, _ = mint_access_token(USER_ID, "Admin", ["red"], 0, TEST_KEY)
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_token(token, "z" * 64)


def test_auth_user_dataclass_frozen():
    u = AuthUser(id=USER_ID, role="Admin", dashboard_roles=["red"], jti="j", token_version=0)
    with pytest.raises(Exception):
        u.role = "Viewer"  # frozen=True
