"""INFRA-02 integration: POST /api/admin/rekey-credentials contract."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "a" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "b" * 64)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

pytestmark = pytest.mark.integration


async def _client():
    from app.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_missing_setup_token_returns_403(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "SETUP_TOKEN", "token-xyz")
    async with await _client() as c:
        r = await c.post("/api/admin/rekey-credentials")
        assert r.status_code == 403
        assert "Invalid or missing setup token" in r.text


@pytest.mark.asyncio
async def test_wrong_setup_token_returns_403(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "SETUP_TOKEN", "correct-token")
    async with await _client() as c:
        r = await c.post(
            "/api/admin/rekey-credentials",
            headers={"X-Setup-Token": "wrong-token"},
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_setup_token_unset_returns_403(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "SETUP_TOKEN", None)
    async with await _client() as c:
        r = await c.post(
            "/api/admin/rekey-credentials",
            headers={"X-Setup-Token": "anything"},
        )
        assert r.status_code == 403


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_missing_rekey_from_secret_returns_400(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "SETUP_TOKEN", "token-xyz")
    monkeypatch.setattr(settings, "REKEY_FROM_SECRET", None)
    async with await _client() as c:
        r = await c.post(
            "/api/admin/rekey-credentials",
            headers={"X-Setup-Token": "token-xyz"},
        )
        assert r.status_code == 400
        assert "REKEY_FROM_SECRET" in r.text


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_rekey_round_trip_reencrypts(db_session, monkeypatch):
    """Seed 2 rows encrypted under OLD_KEY, call rekey, assert all decrypt under NEW_KEY."""
    from app.config import settings
    from app.crypto import decrypt_credentials, encrypt_credentials
    from app.models.sources import Source
    import uuid

    OLD_KEY = "o" * 64
    NEW_KEY = "n" * 64
    monkeypatch.setattr(settings, "SECRET_KEY", NEW_KEY)
    monkeypatch.setattr(settings, "REKEY_FROM_SECRET", OLD_KEY)
    monkeypatch.setattr(settings, "SETUP_TOKEN", "token-xyz")

    # Seed
    src_a = Source(
        id=uuid.uuid4(), name="a", feed_type="rss", url="http://a",
        credentials_enc=encrypt_credentials(OLD_KEY, {"k": "a"}),
    )
    src_b = Source(
        id=uuid.uuid4(), name="b", feed_type="rss", url="http://b",
        credentials_enc=encrypt_credentials(OLD_KEY, {"k": "b"}),
    )
    db_session.add_all([src_a, src_b])
    await db_session.commit()

    # Rekey
    async with await _client() as c:
        r = await c.post(
            "/api/admin/rekey-credentials",
            headers={"X-Setup-Token": "token-xyz"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["rekeyed"] >= 2

    # Verify NEW_KEY decrypts and OLD_KEY no longer does
    await db_session.refresh(src_a)
    await db_session.refresh(src_b)
    assert decrypt_credentials(NEW_KEY, src_a.credentials_enc) == {"k": "a"}
    assert decrypt_credentials(NEW_KEY, src_b.credentials_enc) == {"k": "b"}
    assert src_a.credentials_key_version == 2  # bumped from 1


@pytest.mark.cross_file_pollution
@pytest.mark.asyncio
async def test_rekey_rollback_on_decrypt_failure(db_session, monkeypatch):
    """Seed one row encrypted under a DIFFERENT key; rekey must rollback + return failing id."""
    from app.config import settings
    from app.crypto import encrypt_credentials
    from app.models.sources import Source
    import uuid

    OLD_KEY = "o" * 64
    NEW_KEY = "n" * 64
    WRONG_KEY = "x" * 64

    monkeypatch.setattr(settings, "SECRET_KEY", NEW_KEY)
    monkeypatch.setattr(settings, "REKEY_FROM_SECRET", OLD_KEY)
    monkeypatch.setattr(settings, "SETUP_TOKEN", "token-xyz")

    bad_id = uuid.uuid4()
    bad = Source(
        id=bad_id, name="bad", feed_type="rss", url="http://bad",
        credentials_enc=encrypt_credentials(WRONG_KEY, {"k": "bad"}),  # encrypted with key the rekey doesn't know
    )
    db_session.add(bad)
    await db_session.commit()
    original_blob = bad.credentials_enc

    async with await _client() as c:
        r = await c.post(
            "/api/admin/rekey-credentials",
            headers={"X-Setup-Token": "token-xyz"},
        )
        assert r.status_code == 500
        detail = r.json()["detail"]
        assert detail["error"] == "decrypt_failed"
        assert str(bad_id) in detail["source_ids"]

    # Verify the row blob is UNCHANGED (rollback worked)
    await db_session.refresh(bad)
    assert bad.credentials_enc == original_blob
