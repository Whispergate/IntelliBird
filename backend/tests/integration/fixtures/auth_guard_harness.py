"""PROD-07 auth entrypoint subprocess harness.

Runs `ops/api-entrypoint.sh` (to be added in plan 13-04) in a subshell with a
controlled env so PROD-07 tests can assert:
- exit code 78 (EX_CONFIG) when AUTH_ENABLED is unset/false
- clean startup (dry-run) when AUTH_ENABLED=true + companion vars set

Dry-run contract (to be honoured by the entrypoint in plan 13-04):
- When env var `INTELLIBIRD_ENTRYPOINT_DRY_RUN=1` is set, the entrypoint
  performs all env-guard checks and then exits 0 WITHOUT running
  `alembic upgrade head` or `exec gunicorn`. This lets integration tests
  exercise the guard without starting the real app.
- The guard still fails with exit 78 if AUTH_ENABLED is not 'true'
  regardless of the dry-run flag - guards run before dry-run short-circuit.

Usage:
    result = run_entrypoint({"AUTH_ENABLED": "false"})
    assert result.returncode == 78

    result = run_entrypoint({
        "AUTH_ENABLED": "true",
        "JWT_SIGNING_KEY": "x" * 64,
        "SSO_ISSUER_URL": "https://idp.example/",
        "INTELLIBIRD_ENTRYPOINT_DRY_RUN": "1",
    })
    assert result.returncode == 0
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Repo root is four levels up from this file: backend/tests/integration/fixtures/.
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ENTRYPOINT = REPO_ROOT / "ops" / "api-entrypoint.sh"


def run_entrypoint(
    env: dict[str, str] | None = None,
    *,
    entrypoint_path: Path | None = None,
    dry_run: bool = True,
    timeout: float = 10.0,
) -> subprocess.CompletedProcess:
    """Execute the api entrypoint with controlled env; return CompletedProcess.

    `env`: mapping applied ON TOP of a minimal default env (PATH only). Use to
        set AUTH_ENABLED, JWT_SIGNING_KEY, SSO_ISSUER_URL, etc. per test case.
    `entrypoint_path`: override for tests (default: ops/api-entrypoint.sh).
    `dry_run`: when True, sets INTELLIBIRD_ENTRYPOINT_DRY_RUN=1 so the
        entrypoint skips alembic+gunicorn after guards pass (see module
        docstring contract).
    `timeout`: subprocess timeout in seconds.

    Returns `CompletedProcess` with .returncode, .stdout, .stderr (all text).
    """
    path = entrypoint_path or DEFAULT_ENTRYPOINT
    if not path.exists():
        raise FileNotFoundError(
            f"entrypoint script not found at {path}. Plan 13-04 adds it; "
            "the harness expects it to exist by then."
        )

    merged_env: dict[str, str] = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    if dry_run:
        merged_env["INTELLIBIRD_ENTRYPOINT_DRY_RUN"] = "1"
    if env:
        merged_env.update(env)

    return subprocess.run(
        ["bash", str(path)],
        env=merged_env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
