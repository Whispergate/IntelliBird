"""Settings validator rejects placeholders and short keys — FND-05 / PITFALLS C-3."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _spawn_with_env(secret_key: str) -> subprocess.CompletedProcess[str]:
    """Spawn a subprocess that imports app.config — lets us observe sys.exit(1)."""
    # Inherit the current PATH and the interpreter's site-packages so that
    # pydantic_settings / structlog resolve whether we're running under uv
    # (sys.executable points at the venv) or a plain venv interpreter.
    child_env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "SECRET_KEY": secret_key,
        "DATABASE_URL": "postgresql+asyncpg://u:p@h:5432/d",
        "REDIS_URL": "redis://r:6379/0",
        "HOST": "127.0.0.1",
        "PORT": "8000",
        # Ensure the subprocess finds app.config:
        "PYTHONPATH": str(BACKEND_ROOT),
    }
    return subprocess.run(
        [sys.executable, "-c", "import app.config"],
        cwd=BACKEND_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_rejects_placeholder() -> None:
    for placeholder in ("CHANGEME", "changeme", "your-secret-here", "", "placeholder"):
        result = _spawn_with_env(placeholder)
        assert result.returncode == 1, (
            f"placeholder {placeholder!r} must exit 1, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        combined = result.stdout + result.stderr
        assert "FATAL" in combined and "SECRET_KEY" in combined


def test_rejects_short_key() -> None:
    short = "a" * 31  # 31 chars — one below the threshold
    result = _spawn_with_env(short)
    assert result.returncode == 1, (
        f"31-char SECRET_KEY must exit 1, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "FATAL" in combined and "32" in combined


def test_accepts_valid_key() -> None:
    # 64-hex-char key — what `openssl rand -hex 32` produces
    valid = "a" * 64
    result = _spawn_with_env(valid)
    assert result.returncode == 0, (
        f"valid SECRET_KEY must exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
