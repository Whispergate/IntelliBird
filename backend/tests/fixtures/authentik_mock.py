"""Authentik OIDC mock fixtures - AUTH-01 Wave 0.

Minimal OIDC discovery document + JWKS + sample id_token claims for unit tests of
app/security/oidc.py. These are NOT live captures - they are schema-correct skeletons
sufficient for PyJWT/authlib code paths to run deterministically.

Wave 1 plan 09-02 consumes these when implementing map_groups_to_role.
Wave 2 plan 09-03 consumes these when implementing the callback handler.
"""
from __future__ import annotations

from typing import Any

MOCK_ISSUER_URL = "http://authentik.local/application/o/intellibird/"

AUTHENTIK_DISCOVERY: dict[str, Any] = {
    "issuer": MOCK_ISSUER_URL,
    "authorization_endpoint": f"{MOCK_ISSUER_URL}authorize/",
    "token_endpoint": f"{MOCK_ISSUER_URL}token/",
    "userinfo_endpoint": f"{MOCK_ISSUER_URL}userinfo/",
    "jwks_uri": f"{MOCK_ISSUER_URL}jwks/",
    "response_types_supported": ["code"],
    "subject_types_supported": ["public"],
    "id_token_signing_alg_values_supported": ["RS256"],
    "scopes_supported": ["openid", "profile", "email", "groups"],
    "code_challenge_methods_supported": ["S256"],
}

# Deterministic RS256 public key for test signing roundtrips. Private pair kept
# in the test module below. These are NOT production keys - 2048-bit RSA suitable
# for unit-test speed.
AUTHENTIK_JWKS: dict[str, Any] = {
    "keys": [
        {
            "kty": "RSA",
            "kid": "intellibird-test-key-1",
            "use": "sig",
            "alg": "RS256",
            # N, E set in individual tests via cryptography.hazmat key generation;
            # conftest uses a placeholder here, test setup overrides.
            "n": "placeholder",
            "e": "AQAB",
        }
    ]
}

SAMPLE_ID_TOKEN_CLAIMS: dict[str, Any] = {
    "iss": MOCK_ISSUER_URL,
    "sub": "authentik-test-user-uuid-0001",
    "aud": "intellibird-client",
    "exp": 9999999999,  # 2286 - never expires for test purposes
    "iat": 0,
    "nonce": "test-nonce-0001",
    "email": "test-user@intellibird.local",
    "name": "Test User",
    "groups": [],  # tests fill in per-scenario: ["intellibird-admins"] etc.
}

ADMIN_GROUPS_CLAIM: list[str] = ["intellibird-admins", "org:red-team"]
ANALYST_GROUPS_CLAIM: list[str] = ["intellibird-analysts", "org:blue-team"]
VIEWER_GROUPS_CLAIM: list[str] = ["intellibird-viewers"]
NO_MATCH_GROUPS_CLAIM: list[str] = ["org:some-other-team"]  # -> default Viewer per CONTEXT
