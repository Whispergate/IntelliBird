"""Shared pytest fixtures for IntelliBird backend tests."""
from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any

import pytest


# --- hermetic per-test isolation (TEST-01 / TEST-02) --------------

@pytest.fixture(autouse=True)
def _isolate_global_state() -> Generator[None, None, None]:
    """Hermetic per-test reset of Settings singleton + app.state module + FastAPI app.state.

    TEST-01 / TEST-02. Single autouse fixture covers the three
    non-Redis pollution surfaces. Redis FLUSHDB + DB TRUNCATE live in
    tests/integration/conftest.py because they require session-scoped containers.

    Snapshot strategy: settings.model_dump() returns shallow dict, safe because
    all Settings fields are scalars (str|int|bool|Literal|None) - verified in RESEARCH.
    """
    # --- 1. Lazy imports (avoid breaking unit tests with no app.* deps) ---
    from app.config import settings as _settings
    import app.state as _app_state
    from app.main import app as _fastapi_app

    # --- 2. Snapshot ---
    original_settings_values: dict[str, object] = _settings.model_dump()
    original_decrypt_check = _app_state.decrypt_check
    original_ollama_health = getattr(_fastapi_app.state, "ollama_health", "unknown")

    # --- 3. Reset to known-clean state on entry ---
    _app_state.decrypt_check = "unknown"
    _fastapi_app.state.ollama_health = "unknown"

    yield

    # --- 4. Restore on teardown ---
    for field, value in original_settings_values.items():
        try:
            setattr(_settings, field, value)
        except Exception:
            # Pydantic may reject some setattrs (e.g. computed fields);
            # swallow to keep teardown idempotent.
            pass
    _app_state.decrypt_check = original_decrypt_check
    _fastapi_app.state.ollama_health = original_ollama_health


# --- shared fixtures (AUTH-01..04) ---------------------------------

@pytest.fixture(scope="session")
def jwt_test_signing_key() -> str:
    """Deterministic 64-char hex signing key for JWT tests. Matches Settings validator min 32."""
    return "0" * 32 + "a" * 32


@pytest.fixture
def jwt_settings(monkeypatch: pytest.MonkeyPatch, jwt_test_signing_key: str) -> str:
    """Set JWT_SIGNING_KEY on Settings before any JWT module import. Yields the key."""
    monkeypatch.setenv("JWT_SIGNING_KEY", jwt_test_signing_key)
    # If the settings singleton is already loaded, override the in-memory value too.
    from app.config import settings as _settings
    monkeypatch.setattr(_settings, "JWT_SIGNING_KEY", jwt_test_signing_key, raising=False)
    return jwt_test_signing_key


@pytest.fixture(autouse=False)
def argon2_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap the pwdlib password_hash singleton with fast Argon2 params for unit tests.

    Production: time_cost=3, memory_cost=65536, parallelism=4 (~200ms per hash).
    Test:       time_cost=1, memory_cost=8,    parallelism=1 (~5ms per hash).

    Tests that need this must request the fixture explicitly - autouse would slow the
    test runtime for tests that don't hash anything.
    """
    pytest.importorskip("pwdlib")
    from pwdlib import PasswordHash
    from pwdlib.hashers.argon2 import Argon2Hasher

    fast_hasher = PasswordHash((
        Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1),
    ))
    # Only patch if the module exists - during Wave 0 the module does not yet exist.
    try:
        from app.security import passwords as pw_module  # type: ignore[import-not-found]
        monkeypatch.setattr(pw_module, "password_hash", fast_hasher, raising=False)
    except ImportError:
        pass  # Module lands in Wave 1 plan 09-02


@pytest.fixture
async def redis_flush() -> Generator[None, None, None]:
    """Flush JTI blocklist + lockout keys before and after each test that uses it."""
    try:
        import redis.asyncio as aioredis  # type: ignore[import-not-found]
    except ImportError:
        yield
        return
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    client = aioredis.from_url(url)
    # Scan and delete jwt:* and login:* keys. Plain flushdb avoided to not nuke
    # other test databases on a shared Redis instance.
    for pattern in ("jwt:revoked:*", "login:fails:*", "login:locked:*"):
        keys = [k async for k in client.scan_iter(match=pattern)]
        if keys:
            await client.delete(*keys)
    yield
    for pattern in ("jwt:revoked:*", "login:fails:*", "login:locked:*"):
        keys = [k async for k in client.scan_iter(match=pattern)]
        if keys:
            await client.delete(*keys)
    await client.aclose()


@pytest.fixture
def mock_oidc_jwks() -> dict[str, Any]:
    """Import-and-return the shared Authentik JWKS + token + discovery stubs."""
    from backend.tests.fixtures.authentik_mock import AUTHENTIK_DISCOVERY, AUTHENTIK_JWKS
    return {"discovery": AUTHENTIK_DISCOVERY, "jwks": AUTHENTIK_JWKS}

