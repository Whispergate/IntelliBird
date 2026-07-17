"""INFRA-01/02/04: Settings gains REKEY_FROM_SECRET, SETUP_TOKEN, AUTH_ENABLED."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
VALID_KEY = "a" * 64


def _spawn(env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    child_env = {
        "PATH": os.environ.get("PATH", ""),
        "SECRET_KEY": VALID_KEY,
        "JWT_SIGNING_KEY": VALID_KEY, # required field; must be present in all spawns
        "DATABASE_URL": "postgresql+asyncpg://u:p@h:5432/d",
        "REDIS_URL": "redis://r:6379/0",
        "PYTHONPATH": str(BACKEND_ROOT),
    }
    child_env.update(env_overrides)
    code = (
        "import app.config as c; "
        "print(repr(c.settings.REKEY_FROM_SECRET)); "
        "print(repr(c.settings.SETUP_TOKEN)); "
        "print(repr(c.settings.AUTH_ENABLED))"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_ROOT, env=child_env,
        capture_output=True, text=True, timeout=30,
    )


def test_rekey_from_secret_defaults_none() -> None:
    result = _spawn({})
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == "None"


def test_setup_token_defaults_none() -> None:
    result = _spawn({})
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[1] == "None"


def test_auth_enabled_defaults_false() -> None:
    result = _spawn({})
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[2] == "False"


def test_rekey_from_secret_not_subject_to_placeholder_validator() -> None:
    # Old key CHANGEME (pre-rotation placeholder) must NOT trigger sys.exit(1).
    result = _spawn({"REKEY_FROM_SECRET": "CHANGEME"})
    assert result.returncode == 0, (
        f"REKEY_FROM_SECRET=CHANGEME unexpectedly exited {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert result.stdout.splitlines()[0] == "'CHANGEME'"


def test_auth_enabled_reads_env_true() -> None:
    result = _spawn({"AUTH_ENABLED": "true"})
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[2] == "True"


# ---------------------------------------------------------------------------
# AUTH-03: JWT_SIGNING_KEY + SSO_* settings tests
# Uses subprocess pattern (same as tests above) to avoid singleton
# collision with module-level `settings = Settings()` in app.config.
# ---------------------------------------------------------------------------


def test_jwt_signing_key_required() -> None:
    """JWT_SIGNING_KEY is a required Field(...); missing env raises ValidationError (exit 1)."""
    # Omit JWT_SIGNING_KEY from the child env; pydantic raises ValidationError → exit 1
    result = _spawn({"JWT_SIGNING_KEY": ""})  # empty string overrides the default in _spawn
    # pydantic ValidationError from required missing field exits non-zero
    # (module-level Settings() raises, Python prints traceback and exits 1)
    assert result.returncode != 0, (
        "Expected non-zero exit when JWT_SIGNING_KEY is missing/empty\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def _spawn_jwt(jwt_key: str, extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Spawn a subprocess that imports app.config with a specific JWT_SIGNING_KEY."""
    child_env = {
        "PATH": os.environ.get("PATH", ""),
        "SECRET_KEY": VALID_KEY,
        "JWT_SIGNING_KEY": jwt_key,
        "DATABASE_URL": "postgresql+asyncpg://u:p@h:5432/d",
        "REDIS_URL": "redis://r:6379/0",
        "PYTHONPATH": str(BACKEND_ROOT),
    }
    if extra:
        child_env.update(extra)
    return subprocess.run(
        [sys.executable, "-c", "import app.config"],
        cwd=BACKEND_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_jwt_signing_key_placeholder_exits() -> None:
    """reject_placeholders exits 1 on placeholder JWT_SIGNING_KEY."""
    result = _spawn_jwt("changeme")
    assert result.returncode == 1, (
        f"JWT_SIGNING_KEY=changeme must exit 1, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "FATAL" in combined and "JWT_SIGNING_KEY" in combined


def test_jwt_signing_key_too_short_exits() -> None:
    """reject_placeholders exits 1 when JWT_SIGNING_KEY is shorter than 32 chars."""
    result = _spawn_jwt("a" * 16)  # 16 chars — below MIN_SECRET_KEY_LEN
    assert result.returncode == 1, (
        f"Short JWT_SIGNING_KEY must exit 1, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "FATAL" in combined


def test_sso_fields_optional() -> None:
    """SSO_* fields default to None / 'groups' when unset."""
    code = (
        "import app.config as c; "
        "s = c.settings; "
        "print(repr(s.SSO_ISSUER_URL)); "
        "print(repr(s.SSO_CLIENT_ID)); "
        "print(repr(s.SSO_CLIENT_SECRET)); "
        "print(repr(s.SSO_GROUPS_CLAIM)); "
        "print(repr(s.SSO_ADMIN_GROUPS)); "
        "print(repr(s.SSO_ANALYST_GROUPS)); "
        "print(repr(s.SSO_VIEWER_GROUPS))"
    )
    child_env = {
        "PATH": os.environ.get("PATH", ""),
        "SECRET_KEY": VALID_KEY,
        "JWT_SIGNING_KEY": VALID_KEY,
        "DATABASE_URL": "postgresql+asyncpg://u:p@h:5432/d",
        "REDIS_URL": "redis://r:6379/0",
        "PYTHONPATH": str(BACKEND_ROOT),
        # Deliberately NO SSO_* vars set
    }
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Expected exit 0 with valid keys and no SSO_* vars\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    lines = result.stdout.splitlines()
    assert lines[0] == "None"           # SSO_ISSUER_URL
    assert lines[1] == "None"           # SSO_CLIENT_ID
    assert lines[2] == "None"           # SSO_CLIENT_SECRET
    assert lines[3] == "'groups'"       # SSO_GROUPS_CLAIM default
    assert lines[4] == "None"           # SSO_ADMIN_GROUPS
    assert lines[5] == "None"           # SSO_ANALYST_GROUPS
    assert lines[6] == "None"           # SSO_VIEWER_GROUPS
