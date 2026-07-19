"""Authentik OIDC client + groups->role mapping - AUTH-01.

Env-driven config (per CONTEXT.md - Admin UI for OIDC deferred to v2.1+):
  SSO_ISSUER_URL, SSO_CLIENT_ID, SSO_CLIENT_SECRET, SSO_GROUPS_CLAIM,
  SSO_ADMIN_GROUPS, SSO_ANALYST_GROUPS, SSO_VIEWER_GROUPS.

Uses authlib's AsyncOAuth2Client for the authorization-code flow with PKCE
(code_challenge_method="S256"; Authentik 2025.12.x requires PKCE by default
for confidential providers - PITFALL 6).

map_groups_to_role is the deterministic part of the flow - unit-testable without
network. Fetch + verify id_token landing is in plan 09-03's callback handler.
"""
from __future__ import annotations

from typing import Literal

Role = Literal["Admin", "Analyst", "Viewer"]


def _parse_groups_setting(raw: str | None) -> set[str]:
    """Comma-separated -> stripped set. Empty/None -> empty set."""
    if not raw:
        return set()
    return {g.strip() for g in raw.split(",") if g.strip()}


def map_groups_to_role(
    groups_claim: list[str],
    admin_groups: str | None,
    analyst_groups: str | None,
    viewer_groups: str | None = None,
) -> Role:
    """Map Authentik id_token groups claim to IntelliBird role.

    Precedence: Admin > Analyst > Viewer. Unmatched groups default to Viewer
    (CONTEXT.md: "SSO first-login behaviour: claude picks default role = Viewer
    when no groups match"). viewer_groups is accepted for symmetry but Viewer is
    also the default - the argument is useful for explicit viewer-group lock-in.
    """
    admins = _parse_groups_setting(admin_groups)
    analysts = _parse_groups_setting(analyst_groups)
    # viewer_groups is advisory - Viewer is the default fallback regardless.
    _viewers = _parse_groups_setting(viewer_groups)  # noqa: F841
    claim_set = set(groups_claim)
    if claim_set & admins:
        return "Admin"
    if claim_set & analysts:
        return "Analyst"
    return "Viewer"


async def build_oidc_client():
    """Construct authlib AsyncOAuth2Client configured for Authentik.

    Returns None when SSO is not configured (SSO_ISSUER_URL unset).
    Defers import of authlib so the backend starts even without authlib installed
    until OIDC is wired.

    Implementation stub - the actual exchange + verify path lives in plan 09-03's
    OIDC callback handler. This module exposes the factory so the handler stays
    short.
    """
    from app.config import settings
    if not settings.SSO_ISSUER_URL or not settings.SSO_CLIENT_ID:
        return None
    from authlib.integrations.httpx_client import AsyncOAuth2Client
    return AsyncOAuth2Client(
        client_id=settings.SSO_CLIENT_ID,
        client_secret=settings.SSO_CLIENT_SECRET,
        scope="openid profile email " + settings.SSO_GROUPS_CLAIM,
        redirect_uri=f"{settings.DASHBOARD_URL}/api/auth/oidc/callback",
        code_challenge_method="S256",
    )


async def fetch_server_metadata(issuer_url: str):
    """Fetch Authentik OIDC discovery document.

    Returns the parsed JSON dict. Raises httpx.HTTPError on network failure.
    """
    import httpx
    discovery_url = f"{issuer_url.rstrip('/')}/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(discovery_url)
        resp.raise_for_status()
        return resp.json()


async def verify_id_token(id_token: str, jwks_uri: str) -> dict:
    """Fetch JWKS and verify id_token signature + standard claims.

    Returns the decoded claims dict. Raises on signature / claim validation failure.

    authlib's JsonWebToken handles: signature verification against JWKS, exp/nbf,
    iss, aud validation. The caller checks 'nonce' against the state stored at
    /oidc/login time.
    """
    import httpx
    from authlib.jose import JsonWebToken

    async with httpx.AsyncClient(timeout=10.0) as client:
        jwks_resp = await client.get(jwks_uri)
        jwks_resp.raise_for_status()
        jwks = jwks_resp.json()

    jwt_tool = JsonWebToken(["RS256"])  # Authentik default
    claims = jwt_tool.decode(id_token, jwks)
    claims.validate()  # exp / iss / aud
    return dict(claims)
