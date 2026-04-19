"""INFRA-03 integration: lifespan canary decrypt against live PG."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "a" * 64)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import uuid  # noqa: E402

import pytest  # noqa: E402

pytestmark = pytest.mark.integration

CANARY_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


@pytest.mark.asyncio
async def test_canary_seeds_when_null(db_session, monkeypatch):
    from app.config import settings
    from app.main import _run_startup_decrypt_check
    from app.models.sources import Source
    from sqlalchemy import select, update

    # Force canary credentials_enc back to NULL (migration-initial state)
    await db_session.execute(
        update(Source).where(Source.id == CANARY_ID).values(credentials_enc=None)
    )
    await db_session.commit()

    monkeypatch.setattr(settings, "SECRET_KEY", "k" * 64)
    result = await _run_startup_decrypt_check()
    assert result == "ok"

    row = (await db_session.execute(select(Source).where(Source.id == CANARY_ID))).scalar_one()
    assert row.credentials_enc is not None


@pytest.mark.asyncio
async def test_canary_ok_on_round_trip(db_session, monkeypatch):
    from app.config import settings
    from app.crypto import encrypt_credentials
    from app.main import CANARY_PLAINTEXT, _run_startup_decrypt_check
    from app.models.sources import Source
    from sqlalchemy import update

    key = "k" * 64
    monkeypatch.setattr(settings, "SECRET_KEY", key)
    await db_session.execute(
        update(Source).where(Source.id == CANARY_ID).values(
            credentials_enc=encrypt_credentials(key, CANARY_PLAINTEXT)
        )
    )
    await db_session.commit()

    result = await _run_startup_decrypt_check()
    assert result == "ok"


@pytest.mark.asyncio
async def test_canary_failed_on_wrong_key(db_session, monkeypatch, caplog):
    import logging
    from app.config import settings
    from app.crypto import encrypt_credentials
    from app.main import CANARY_PLAINTEXT, _run_startup_decrypt_check
    from app.models.sources import Source
    from sqlalchemy import update

    # Encrypt under KEY_A
    await db_session.execute(
        update(Source).where(Source.id == CANARY_ID).values(
            credentials_enc=encrypt_credentials("a" * 64, CANARY_PLAINTEXT)
        )
    )
    await db_session.commit()

    # Run check under KEY_B
    monkeypatch.setattr(settings, "SECRET_KEY", "b" * 64)
    with caplog.at_level(logging.CRITICAL):
        result = await _run_startup_decrypt_check()
    assert result == "failed"


@pytest.mark.asyncio
async def test_canary_unknown_when_row_missing(db_session, monkeypatch):
    from app.config import settings
    from app.main import _run_startup_decrypt_check
    from app.models.sources import Source
    from sqlalchemy import delete

    # Remove canary row entirely
    await db_session.execute(delete(Source).where(Source.id == CANARY_ID))
    await db_session.commit()

    monkeypatch.setattr(settings, "SECRET_KEY", "k" * 64)
    result = await _run_startup_decrypt_check()
    assert result == "unknown"
