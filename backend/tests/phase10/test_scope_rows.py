"""test_scope_rows — PRJ-02 validators + persistence (plan 10-04).

Unit-level tests cover the validator functions in scope_validators.py directly
(pure functions, no DB). The final `test_each_scope_type_persists` is the
integration test that exercises POST /api/projects/{id}/scope end-to-end for
each of the 7 scope types.
"""
from __future__ import annotations

import uuid as _uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# NO module-level pytestmark — validator unit tests are pure; the single
# integration test marks itself explicitly.
from app.services.scope_validators import (
    validate_as_number,
    validate_certificate_hash,
    validate_cidr,
    validate_fqdn,
    validate_scope_row_value,
)


# ---------------------------------------------------------------------------
# Unit tests — pure functions, no DB
# ---------------------------------------------------------------------------


def test_cidr_validator() -> None:
    """CIDR validator accepts IPv4/IPv6 and rejects malformed input."""
    assert validate_cidr("10.0.0.0/24") == "10.0.0.0/24"
    # strip + strict=False normalisation (host bits set on /16 reduce to /16 net)
    assert validate_cidr("  192.168.1.0/16 ") == "192.168.0.0/16"
    # IPv6 round-trips
    assert validate_cidr("2001:db8::/32") == "2001:db8::/32"
    with pytest.raises(ValueError, match="valid CIDR"):
        validate_cidr("not-a-cidr")
    with pytest.raises(ValueError, match="valid CIDR"):
        validate_cidr("300.1.1.1/24")


def test_fqdn_validator() -> None:
    """FQDN validator accepts valid domains and rejects malformed input."""
    assert validate_fqdn("Example.COM") == "example.com"
    assert validate_fqdn("a.b.example.com") == "a.b.example.com"
    assert validate_fqdn("  trim-me.io  ") == "trim-me.io"
    with pytest.raises(ValueError, match="valid domain"):
        validate_fqdn("not a domain")
    with pytest.raises(ValueError, match="valid domain"):
        validate_fqdn("example")
    with pytest.raises(ValueError, match="valid domain"):
        validate_fqdn(".example.com")


def test_as_number_validator() -> None:
    """AS number validator accepts 'AS12345' or '12345'; range 1..2^32-1."""
    assert validate_as_number("AS12345") == "12345"
    assert validate_as_number("12345") == "12345"
    assert validate_as_number("as65001") == "65001"
    assert validate_as_number("  4294967295 ") == "4294967295"
    with pytest.raises(ValueError, match="positive integer"):
        validate_as_number("AS-1")
    with pytest.raises(ValueError, match="positive integer"):
        validate_as_number("abc")
    with pytest.raises(ValueError, match="positive integer"):
        validate_as_number("0")
    with pytest.raises(ValueError, match="positive integer"):
        validate_as_number("4294967296")


def test_certificate_hash_validator() -> None:
    """Cert validator accepts SHA-1 (40 hex) or SHA-256 (64 hex), strips ':'."""
    sha1 = "da39a3ee5e6b4b0d3255bfef95601890afd80709"
    assert validate_certificate_hash(sha1.upper()) == sha1
    sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    # Colon-separated standard fingerprint display format
    assert (
        validate_certificate_hash(":".join(sha256[i:i + 2] for i in range(0, 64, 2)))
        == sha256
    )
    with pytest.raises(ValueError):
        validate_certificate_hash("abc")
    with pytest.raises(ValueError):
        validate_certificate_hash("z" * 40)  # non-hex


def test_both_false_invalid() -> None:
    """ScopeRowCreate Pydantic model rejects both active_test_scope=False and intel_scope=False."""
    from pydantic import ValidationError

    from app.schemas.projects import ScopeRowCreate

    with pytest.raises(ValidationError, match="Row must target at least"):
        ScopeRowCreate(
            scope_type="keyword",
            value="x",
            active_test_scope=False,
            intel_scope=False,
        )


def test_scope_type_dispatch() -> None:
    """Dispatch covers all 7 scope types and rejects unknown types."""
    assert validate_scope_row_value("ip_range", "10.0.0.0/8") == "10.0.0.0/8"
    assert validate_scope_row_value("domain", "EXAMPLE.COM") == "example.com"
    assert validate_scope_row_value("as_number", "AS65001") == "65001"
    assert (
        validate_scope_row_value(
            "certificate", "da39a3ee5e6b4b0d3255bfef95601890afd80709"
        )
        == "da39a3ee5e6b4b0d3255bfef95601890afd80709"
    )
    assert validate_scope_row_value("keyword", "  threat  ") == "threat"
    assert validate_scope_row_value("service", "nginx/1.18") == "nginx/1.18"
    assert validate_scope_row_value("whois", "acme corp") == "acme corp"
    with pytest.raises(ValueError):
        validate_scope_row_value("not_a_type", "x")


# ---------------------------------------------------------------------------
# Integration test — POST /api/projects/{id}/scope for each of the 7 types
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(db_engine, monkeypatch):
    """AsyncClient wired to app with get_session overridden to the test DB engine."""
    from app.config import settings
    from app.database import get_session
    from app.main import app
    import app.middleware.auth as auth_mod

    monkeypatch.setattr(settings, "AUTH_ENABLED", True, raising=False)

    async def _fake_tv(user_id: str):
        return 0

    async def _fake_revoked(jti: str) -> bool:
        return False

    monkeypatch.setattr(auth_mod, "_get_cached_token_version", _fake_tv)
    monkeypatch.setattr(auth_mod, "_is_jti_revoked", _fake_revoked)

    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override_session():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _override_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.mark.integration
async def test_each_scope_type_persists(client: AsyncClient, users_matrix) -> None:
    """Create 1 row per each of 7 scope types using admin (bypasses membership)."""
    admin_token = users_matrix["tokens"]["admin"]
    proj = (
        await client.post(
            "/api/projects",
            json={"name": "Scope Type Parade", "engagement_type": "internal"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()
    pid = proj["id"]

    samples = [
        ("keyword", "apt"),
        ("service", "ssh"),
        ("domain", "example.com"),
        ("certificate", "da39a3ee5e6b4b0d3255bfef95601890afd80709"),
        ("whois", "acme"),
        ("as_number", "AS65000"),
        ("ip_range", "10.0.0.0/24"),
    ]
    for st, v in samples:
        r = await client.post(
            f"/api/projects/{pid}/scope",
            json={"scope_type": st, "value": v},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 201, f"{st}={v}: {r.text}"

    listing = (
        await client.get(
            f"/api/projects/{pid}/scope",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()
    assert len(listing) == 7
    assert sorted({row["scope_type"] for row in listing}) == sorted(
        dict(samples).keys()
    )


@pytest.mark.integration
async def test_invalid_cidr_returns_422(client: AsyncClient, users_matrix) -> None:
    """POST with scope_type=ip_range and invalid CIDR returns 422 + exact UI-SPEC copy."""
    admin_token = users_matrix["tokens"]["admin"]
    proj = (
        await client.post(
            "/api/projects",
            json={"name": "Invalid CIDR", "engagement_type": "internal"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    ).json()
    pid = proj["id"]
    r = await client.post(
        f"/api/projects/{pid}/scope",
        json={"scope_type": "ip_range", "value": "not-a-cidr"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "Enter a valid CIDR block, e.g. 10.0.0.0/24."
