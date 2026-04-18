"""ops/.env.example ships placeholder SECRET_KEY + openssl hint (C-3 hygiene)."""
from __future__ import annotations

from pathlib import Path

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / "ops" / ".env.example"


def test_env_example_exists() -> None:
    assert ENV_EXAMPLE.exists(), f"missing {ENV_EXAMPLE}"


def test_secret_key_is_placeholder() -> None:
    """.env.example MUST ship a placeholder so the validator rejects a
    copy-without-edit — this is the guard rail that forces the operator
    to generate a real key.
    """
    content = ENV_EXAMPLE.read_text()
    assert "SECRET_KEY=CHANGEME" in content, (
        ".env.example must ship SECRET_KEY=CHANGEME so the pydantic "
        "validator rejects an unmodified copy."
    )


def test_env_example_has_openssl_hint() -> None:
    content = ENV_EXAMPLE.read_text()
    assert "openssl rand -hex 32" in content, (
        ".env.example must include the openssl command for key generation."
    )


def test_env_example_uses_asyncpg_dsn() -> None:
    content = ENV_EXAMPLE.read_text()
    assert "postgresql+asyncpg://" in content, (
        "DATABASE_URL must use the asyncpg driver — required by Alembic "
        "env.py and SQLAlchemy async engine."
    )


def test_env_example_defaults_host_loopback() -> None:
    content = ENV_EXAMPLE.read_text()
    assert "HOST=127.0.0.1" in content, (
        ".env.example must ship HOST=127.0.0.1 as the default; changing it "
        "triggers the no-auth banner in the web stub (FND-04)."
    )
