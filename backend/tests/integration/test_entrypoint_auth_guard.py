"""PROD-07: api container entrypoint refuse-to-start guard.

Tests `ops/api-entrypoint.sh` via the Wave-0 auth_guard_harness.run_entrypoint
helper. Guards must reject AUTH_ENABLED != 'true' with exit 78 (EX_CONFIG)
and must reject AUTH_ENABLED=true without the companion env vars
(JWT_SIGNING_KEY, SSO_ISSUER_URL).

These tests run the entrypoint as a subprocess with a controlled env; they
DO NOT require Docker or the full stack. They only need `bash` on PATH and
the entrypoint script present at ops/api-entrypoint.sh.
"""
from __future__ import annotations

import shutil

import pytest

from tests.integration.fixtures.auth_guard_harness import (
    DEFAULT_ENTRYPOINT,
    run_entrypoint,
)

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None,
    reason="bash not available on PATH",
)


def _require_script() -> None:
    if not DEFAULT_ENTRYPOINT.exists():
        pytest.fail(
            f"ops/api-entrypoint.sh missing at {DEFAULT_ENTRYPOINT}. "
            "Plan 13-04 Task 4.1 must land before this test can run."
        )


def test_entrypoint_refuses_without_auth() -> None:
    """No AUTH_ENABLED in env → exit 78 with clear error citing AUTH_ENABLED."""
    _require_script()
    # dry_run=False so we don't mask the guard with the short-circuit
    result = run_entrypoint(env={}, dry_run=False)
    assert result.returncode == 78, (
        f"expected exit 78 (EX_CONFIG) when AUTH_ENABLED unset; "
        f"got {result.returncode}. stderr={result.stderr!r}"
    )
    assert "AUTH_ENABLED" in result.stderr


def test_entrypoint_refuses_auth_false() -> None:
    """AUTH_ENABLED=false → exit 78."""
    _require_script()
    result = run_entrypoint(env={"AUTH_ENABLED": "false"}, dry_run=False)
    assert result.returncode == 78
    assert "AUTH_ENABLED" in result.stderr


def test_entrypoint_requires_jwt_key() -> None:
    """AUTH_ENABLED=true but no JWT_SIGNING_KEY → non-zero exit mentioning JWT_SIGNING_KEY."""
    _require_script()
    result = run_entrypoint(
        env={"AUTH_ENABLED": "true"},
        dry_run=False,
    )
    assert result.returncode != 0
    # bash's `: "${VAR:?msg}"` emits the var name and the message to stderr.
    assert "JWT_SIGNING_KEY" in result.stderr


def test_entrypoint_requires_sso_issuer() -> None:
    """AUTH_ENABLED=true + JWT key but no SSO_ISSUER_URL → non-zero exit mentioning SSO_ISSUER_URL."""
    _require_script()
    result = run_entrypoint(
        env={
            "AUTH_ENABLED": "true",
            "JWT_SIGNING_KEY": "x" * 64,
        },
        dry_run=False,
    )
    assert result.returncode != 0
    assert "SSO_ISSUER_URL" in result.stderr


def test_entrypoint_dry_run_ok() -> None:
    """All guards satisfied + dry-run flag → exit 0 without running app."""
    _require_script()
    result = run_entrypoint(
        env={
            "AUTH_ENABLED": "true",
            "JWT_SIGNING_KEY": "x" * 64,
            "SSO_ISSUER_URL": "https://idp.example/",
        },
        dry_run=True,
    )
    assert result.returncode == 0, (
        f"expected exit 0 on dry-run with all guards satisfied; "
        f"got {result.returncode}. stderr={result.stderr!r}"
    )
