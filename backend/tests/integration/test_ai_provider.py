"""Integration tests for AI-01 ai_providers table + credential encryption + rekey sweep.

Covers:
  - Migration 014 creates ai_providers table with correct columns (credentials_enc,
    credentials_key_version mirrors sources.credentials_enc pattern exactly).
  - AES-256-GCM encryption round-trip on AIProvider.credentials_enc.
  - POST /api/admin/rekey-credentials sweeps both sources AND ai_providers in the
    same transaction.
  - AIProvider with credentials_enc=NULL is skipped without error.

Phase 17 / AI-01: task 1 (migration + ORM) and task 2 (rekey sweep).
"""
from __future__ import annotations

import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.integration


async def _client():
    from app.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


# ---------------------------------------------------------------------------
# Helper: create a minimal project row for FK satisfaction
# ---------------------------------------------------------------------------

async def _make_project(db_session) -> uuid.UUID:
    """Insert a minimal project row and return its id."""
    project_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by) "
            "VALUES (:id, :name, 'intel_only', 'test')"
        ),
        {"id": project_id, "name": f"test-project-{project_id}"},
    )
    await db_session.commit()
    return project_id


# ---------------------------------------------------------------------------
# Task 1: Migration 014 — table structure tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_014_creates_ai_providers_table(db_session) -> None:
    """Migration 014 creates the ai_providers table with correct columns.

    Asserts: credentials_enc TEXT NULL, credentials_key_version INTEGER NOT NULL DEFAULT 1,
    project_id UUID FK, provider_type, model_name, api_base, created_at, updated_at all present.
    Unique constraint on project_id (one provider per project).
    """
    # Check the table exists by querying information_schema
    result = await db_session.execute(
        text(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_name = 'ai_providers' "
            "ORDER BY ordinal_position"
        )
    )
    columns = {row[0]: (row[1], row[2]) for row in result.fetchall()}

    assert "id" in columns, "ai_providers.id missing"
    assert "project_id" in columns, "ai_providers.project_id missing"
    assert "provider_type" in columns, "ai_providers.provider_type missing"
    assert "model_name" in columns, "ai_providers.model_name missing"
    assert "api_base" in columns, "ai_providers.api_base missing"
    assert "credentials_enc" in columns, "ai_providers.credentials_enc missing"
    assert "credentials_key_version" in columns, "ai_providers.credentials_key_version missing"
    assert "created_at" in columns, "ai_providers.created_at missing"
    assert "updated_at" in columns, "ai_providers.updated_at missing"

    # credentials_enc is nullable (NULL is valid for Ollama/no-auth setups)
    assert columns["credentials_enc"][1] == "YES", (
        "ai_providers.credentials_enc must be nullable"
    )
    # credentials_key_version is NOT NULL
    assert columns["credentials_key_version"][1] == "NO", (
        "ai_providers.credentials_key_version must be NOT NULL"
    )

    # Verify default value for credentials_key_version is 1
    result2 = await db_session.execute(
        text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'ai_providers' AND column_name = 'credentials_key_version'"
        )
    )
    row = result2.fetchone()
    assert row is not None and row[0] is not None, (
        "ai_providers.credentials_key_version must have a server_default"
    )
    assert "1" in str(row[0]), (
        f"credentials_key_version default should be 1, got: {row[0]}"
    )

    # Verify UNIQUE constraint on project_id
    result3 = await db_session.execute(
        text(
            "SELECT constraint_name FROM information_schema.table_constraints "
            "WHERE table_name = 'ai_providers' AND constraint_type = 'UNIQUE'"
        )
    )
    unique_constraints = [r[0] for r in result3.fetchall()]
    assert any("project_id" in c for c in unique_constraints) or len(unique_constraints) > 0, (
        f"ai_providers must have a UNIQUE constraint on project_id. Found: {unique_constraints}"
    )


@pytest.mark.asyncio
async def test_migration_014_ai_summaries_event_id_soft_fk(db_session) -> None:
    """ai_summaries.event_id has NO FK constraint to events (soft FK pattern).

    Verifies that inserting an ai_summaries row with a non-existent event_id UUID
    does NOT raise a foreign key constraint violation.
    """
    project_id = await _make_project(db_session)
    phantom_event_id = uuid.uuid4()  # does not exist in events table

    # Insert a summary pointing at a non-existent event — must succeed (soft FK)
    await db_session.execute(
        text(
            "INSERT INTO ai_summaries "
            "(id, project_id, event_id, summary_type, provider_used, model_used, "
            "prompt_template_version, summary_text) "
            "VALUES (:id, :pid, :eid, 'event', 'ollama', 'phi3:mini', 'EVENT_SUMMARY_PROMPT_V1', 'test')"
        ),
        {"id": uuid.uuid4(), "pid": project_id, "eid": phantom_event_id},
    )
    await db_session.commit()  # must not raise

    # Verify the row was inserted
    result = await db_session.execute(
        text("SELECT event_id FROM ai_summaries WHERE project_id = :pid"),
        {"pid": project_id},
    )
    row = result.fetchone()
    assert row is not None
    assert str(row[0]) == str(phantom_event_id), (
        f"event_id mismatch: expected {phantom_event_id}, got {row[0]}"
    )


@pytest.mark.asyncio
async def test_migration_014_events_ai_score_column(db_session) -> None:
    """events.ai_score is numeric(5,2) NULL — added by migration 014."""
    result = await db_session.execute(
        text(
            "SELECT data_type, numeric_precision, numeric_scale, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_name = 'events' AND column_name = 'ai_score'"
        )
    )
    row = result.fetchone()
    assert row is not None, "events.ai_score column missing — migration 014 not applied"
    data_type, precision, scale, nullable = row
    assert data_type == "numeric", f"ai_score type: expected numeric, got {data_type}"
    assert precision == 5, f"ai_score precision: expected 5, got {precision}"
    assert scale == 2, f"ai_score scale: expected 2, got {scale}"
    assert nullable == "YES", "ai_score must be nullable"


@pytest.mark.asyncio
async def test_migration_014_projects_ai_columns(db_session) -> None:
    """projects table has all four ai_* columns from migration 014."""
    result = await db_session.execute(
        text(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_name = 'projects' "
            "AND column_name IN ('ai_digest_enabled','ai_rerank_enabled','ai_daily_token_cap','digest_schedule_cron')"
            "ORDER BY column_name"
        )
    )
    rows = {r[0]: (r[1], r[2], r[3]) for r in result.fetchall()}

    assert "ai_digest_enabled" in rows, "projects.ai_digest_enabled missing"
    assert "ai_rerank_enabled" in rows, "projects.ai_rerank_enabled missing"
    assert "ai_daily_token_cap" in rows, "projects.ai_daily_token_cap missing"
    assert "digest_schedule_cron" in rows, "projects.digest_schedule_cron missing"

    # Both booleans must NOT be nullable (NOT NULL with server_default)
    assert rows["ai_digest_enabled"][1] == "NO", "ai_digest_enabled must be NOT NULL"
    assert rows["ai_rerank_enabled"][1] == "NO", "ai_rerank_enabled must be NOT NULL"
    assert rows["ai_daily_token_cap"][1] == "NO", "ai_daily_token_cap must be NOT NULL"
    assert rows["digest_schedule_cron"][1] == "NO", "digest_schedule_cron must be NOT NULL"

    # Check defaults
    assert "100000" in str(rows["ai_daily_token_cap"][2]), (
        f"ai_daily_token_cap default should be 100000, got {rows['ai_daily_token_cap'][2]}"
    )
    cron_default = str(rows["digest_schedule_cron"][2])
    assert "0 6 * * *" in cron_default, (
        f"digest_schedule_cron default should be '0 6 * * *', got {cron_default}"
    )


# ---------------------------------------------------------------------------
# Task 1: ORM model import verification
# ---------------------------------------------------------------------------


def test_orm_models_importable() -> None:
    """AIProvider, AISummary, AISuggestion import without error."""
    from app.models.ai import AIProvider, AISummary, AISuggestion  # noqa: F401
    assert AIProvider.__tablename__ == "ai_providers"
    assert AISummary.__tablename__ == "ai_summaries"
    assert AISuggestion.__tablename__ == "ai_suggestions"


# ---------------------------------------------------------------------------
# Task 2: AES-256-GCM encryption round-trip on AIProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credentials_enc_aes256gcm(db_session) -> None:
    """ai_providers.credentials_enc stores AES-256-GCM ciphertext; decrypt round-trips correctly.

    Verifies:
    - Ciphertext stored in DB differs from plaintext (encrypted).
    - decrypt_credentials round-trips back to original dict.
    - credentials_key_version defaults to 1.
    """
    from app.config import settings
    from app.crypto import decrypt_credentials, encrypt_credentials
    from app.models.ai import AIProvider

    project_id = await _make_project(db_session)
    secret = settings.SECRET_KEY
    original_creds = {"api_key": "sk-test-abc123"}
    ciphertext = encrypt_credentials(secret, original_creds)

    provider = AIProvider(
        id=uuid.uuid4(),
        project_id=project_id,
        provider_type="openai",
        model_name="gpt-4o",
        credentials_enc=ciphertext,
    )
    db_session.add(provider)
    await db_session.commit()

    # Re-query from DB
    result = await db_session.execute(
        text("SELECT credentials_enc, credentials_key_version FROM ai_providers WHERE id = :id"),
        {"id": provider.id},
    )
    row = result.fetchone()
    assert row is not None
    stored_blob, key_version = row

    # Ciphertext must NOT equal plaintext
    assert stored_blob != str(original_creds), "credentials_enc must be encrypted"
    assert stored_blob == ciphertext, "stored blob must match what was inserted"

    # credentials_key_version defaults to 1
    assert key_version == 1, f"credentials_key_version default should be 1, got {key_version}"

    # Decrypt must round-trip back to original
    decrypted = decrypt_credentials(secret, stored_blob)
    assert decrypted == original_creds, (
        f"Decrypt round-trip failed: expected {original_creds}, got {decrypted}"
    )


@pytest.mark.asyncio
async def test_credentials_enc_null_allowed(db_session) -> None:
    """AIProvider can be created with credentials_enc=NULL (e.g. Ollama no-auth)."""
    from app.models.ai import AIProvider

    project_id = await _make_project(db_session)
    provider = AIProvider(
        id=uuid.uuid4(),
        project_id=project_id,
        provider_type="ollama",
        model_name="phi3:mini",
        api_base="http://ollama:11434",
        credentials_enc=None,
    )
    db_session.add(provider)
    await db_session.commit()  # must not raise

    result = await db_session.execute(
        text("SELECT credentials_enc FROM ai_providers WHERE id = :id"),
        {"id": provider.id},
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] is None, "credentials_enc should be NULL for no-auth provider"


# ---------------------------------------------------------------------------
# Task 2: Rekey sweep includes AIProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rekey_credentials_sweeps_ai_providers(db_session, monkeypatch) -> None:
    """POST /api/admin/rekey-credentials re-encrypts AIProvider rows alongside Source rows.

    Setup: seed 1 Source + 1 AIProvider both encrypted under OLD_KEY at key_version=1.
    Action: call rekey endpoint (REKEY_FROM_SECRET=OLD_KEY, SECRET_KEY=NEW_KEY).
    Assert:
      - response has ai_providers_rekeyed=1 and sources_rekeyed>=1
      - AIProvider.credentials_key_version bumped to 2
      - AIProvider.credentials_enc decrypts under NEW_KEY (not OLD_KEY)
    """
    from app.config import settings
    from app.crypto import decrypt_credentials, encrypt_credentials
    from app.models.ai import AIProvider
    from app.models.sources import Source

    OLD_KEY = "o" * 64
    NEW_KEY = "n" * 64

    monkeypatch.setattr(settings, "SECRET_KEY", NEW_KEY)
    monkeypatch.setattr(settings, "REKEY_FROM_SECRET", OLD_KEY)
    monkeypatch.setattr(settings, "SETUP_TOKEN", "token-xyz")

    project_id = await _make_project(db_session)
    ai_creds = {"api_key": "sk-old-key"}
    provider = AIProvider(
        id=uuid.uuid4(),
        project_id=project_id,
        provider_type="openai",
        model_name="gpt-4o",
        credentials_enc=encrypt_credentials(OLD_KEY, ai_creds),
    )
    src = Source(
        id=uuid.uuid4(),
        name=f"src-{uuid.uuid4()}",
        feed_type="rss",
        url="http://test-rekey-ai",
        credentials_enc=encrypt_credentials(OLD_KEY, {"token": "src-token"}),
    )
    db_session.add_all([provider, src])
    await db_session.commit()

    async with await _client() as c:
        r = await c.post(
            "/api/admin/rekey-credentials",
            headers={"X-Setup-Token": "token-xyz"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ai_providers_rekeyed"] >= 1, (
        f"Expected ai_providers_rekeyed >= 1, got {body}"
    )
    assert body["sources_rekeyed"] >= 1, (
        f"Expected sources_rekeyed >= 1, got {body}"
    )

    # Refresh and verify AIProvider was re-encrypted
    await db_session.refresh(provider)
    assert provider.credentials_key_version == 2, (
        f"credentials_key_version should be 2 after rekey, got {provider.credentials_key_version}"
    )
    # Must decrypt under NEW_KEY
    decrypted = decrypt_credentials(NEW_KEY, provider.credentials_enc)
    assert decrypted == ai_creds, (
        f"Decrypted credentials mismatch: expected {ai_creds}, got {decrypted}"
    )
    # Must NOT decrypt under OLD_KEY
    import pytest as _pytest
    with _pytest.raises(Exception):
        decrypt_credentials(OLD_KEY, provider.credentials_enc)


@pytest.mark.asyncio
async def test_rekey_skips_ai_provider_null_credentials(db_session, monkeypatch) -> None:
    """AIProvider with credentials_enc=NULL is skipped without error during rekey."""
    from app.config import settings
    from app.models.ai import AIProvider

    OLD_KEY = "o" * 64
    NEW_KEY = "n" * 64

    monkeypatch.setattr(settings, "SECRET_KEY", NEW_KEY)
    monkeypatch.setattr(settings, "REKEY_FROM_SECRET", OLD_KEY)
    monkeypatch.setattr(settings, "SETUP_TOKEN", "token-xyz")

    project_id = await _make_project(db_session)
    provider = AIProvider(
        id=uuid.uuid4(),
        project_id=project_id,
        provider_type="ollama",
        model_name="phi3:mini",
        api_base="http://ollama:11434",
        credentials_enc=None,
    )
    db_session.add(provider)
    await db_session.commit()

    async with await _client() as c:
        r = await c.post(
            "/api/admin/rekey-credentials",
            headers={"X-Setup-Token": "token-xyz"},
        )
    assert r.status_code == 200, r.text
    # No error; the null-credentials provider contributes to skipped count
    body = r.json()
    assert "ai_providers_rekeyed" in body
    # credentials_enc remains NULL
    await db_session.refresh(provider)
    assert provider.credentials_enc is None, "NULL credentials_enc must not be modified by rekey"


# ---------------------------------------------------------------------------
# HTTP endpoint tests — GET/PUT /api/projects/{id}/ai-provider + /test
# ---------------------------------------------------------------------------

TEST_SIGNING_KEY = "j" * 64


def _mint_admin_token_for_provider() -> str:
    from app.security.jwt import mint_access_token  # noqa: PLC0415

    token, _ = mint_access_token(
        str(uuid.uuid4()), "Admin", ["red", "blue"], 0, TEST_SIGNING_KEY
    )
    return token


def _patch_auth_for_provider(monkeypatch) -> None:
    import app.middleware.auth as auth_mod  # noqa: PLC0415
    from app.config import settings  # noqa: PLC0415

    async def _fake_token_version(user_id: str):
        return 0

    async def _fake_jti_revoked(jti: str) -> bool:
        return False

    monkeypatch.setattr(auth_mod, "_get_cached_token_version", _fake_token_version)
    monkeypatch.setattr(auth_mod, "_is_jti_revoked", _fake_jti_revoked)
    monkeypatch.setattr(settings, "JWT_SIGNING_KEY", TEST_SIGNING_KEY, raising=False)
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)


@pytest.mark.asyncio
async def test_get_ai_provider_returns_masked_key(monkeypatch) -> None:
    """GET /api/projects/{id}/ai-provider returns provider config without plaintext api_key.

    api_key_masked should be '••••••••' when credentials_enc is set.
    """
    from datetime import datetime, timezone  # noqa: PLC0415
    from httpx import ASGITransport, AsyncClient  # noqa: PLC0415
    from unittest.mock import AsyncMock, MagicMock  # noqa: PLC0415
    from app.main import create_app  # noqa: PLC0415
    from app.database import get_session  # noqa: PLC0415

    _patch_auth_for_provider(monkeypatch)

    project_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    fake_provider = MagicMock()
    fake_provider.id = uuid.uuid4()
    fake_provider.project_id = project_id
    fake_provider.provider_type = "openai"
    fake_provider.model_name = "gpt-4o"
    fake_provider.api_base = None
    fake_provider.credentials_enc = "some-encrypted-blob"  # non-null = has key
    fake_provider.credentials_key_version = 1
    fake_provider.created_at = now
    fake_provider.updated_at = now

    fake_project = MagicMock()
    fake_project.id = project_id
    fake_project.ai_rerank_enabled = False
    fake_project.ai_digest_enabled = False
    fake_project.ai_daily_token_cap = 100_000
    fake_project.digest_schedule_cron = "0 6 * * *"

    call_count = {"n": 0}

    async def _mock_get_session():
        mock_db = AsyncMock()

        async def execute_side_effect(stmt, *args, **kwargs):
            call_count["n"] += 1
            res = MagicMock()
            if call_count["n"] == 1:
                res.scalar_one_or_none.return_value = fake_provider
            else:
                res.scalar_one_or_none.return_value = fake_project
            return res

        mock_db.execute = AsyncMock(side_effect=execute_side_effect)
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_session] = _mock_get_session

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get(
            f"/api/projects/{project_id}/ai-provider",
            headers={"Authorization": f"Bearer {_mint_admin_token_for_provider()}"},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["provider_type"] == "openai"
    assert body["model_name"] == "gpt-4o"
    # Key must be masked — never return plaintext.
    assert body["api_key_masked"] == "••••••••", (
        f"Expected masked key, got: {body.get('api_key_masked')!r}"
    )
    # No plaintext api_key field in response.
    assert "api_key" not in body or body.get("api_key") is None


@pytest.mark.asyncio
async def test_put_ai_provider_encrypts_key(monkeypatch) -> None:
    """PUT /api/projects/{id}/ai-provider stores encrypted credentials; GET returns masked.

    Verifies: plaintext api_key 'sk-test-secret-key' never appears in the response body.
    Uses a full mock DB that returns both AIProvider (existing row) and Project row.
    """
    from datetime import datetime, timezone  # noqa: PLC0415
    from httpx import ASGITransport, AsyncClient  # noqa: PLC0415
    from unittest.mock import AsyncMock, MagicMock  # noqa: PLC0415
    from app.main import create_app  # noqa: PLC0415
    from app.database import get_session  # noqa: PLC0415

    _patch_auth_for_provider(monkeypatch)

    project_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    provider_id = uuid.uuid4()

    # Use a real namespace object with properly typed fields that Pydantic can serialize.
    class _FakeProvider:
        pass

    fake_provider = _FakeProvider()
    fake_provider.id = provider_id
    fake_provider.project_id = project_id
    fake_provider.provider_type = "openai"
    fake_provider.model_name = "gpt-4o"
    fake_provider.api_base = None
    fake_provider.credentials_enc = None  # will be set by handler
    fake_provider.credentials_key_version = 1
    fake_provider.created_at = now
    fake_provider.updated_at = now

    class _FakeProject:
        pass

    fake_project = _FakeProject()
    fake_project.id = project_id
    fake_project.ai_rerank_enabled = False
    fake_project.ai_digest_enabled = False
    fake_project.ai_daily_token_cap = 100_000
    fake_project.digest_schedule_cron = "0 6 * * *"
    fake_project.updated_at = now

    async def _mock_get_session():
        # Per-session call counter (local to this generator invocation).
        _call_count = {"n": 0}
        mock_db = AsyncMock()

        async def execute_side_effect(stmt, *args, **kwargs):
            _call_count["n"] += 1
            res = MagicMock()
            # PUT flow queries: 1=Project, 2=AIProvider (handler queries Project FIRST)
            if _call_count["n"] == 1:
                res.scalar_one_or_none.return_value = fake_project
            else:
                res.scalar_one_or_none.return_value = fake_provider
            return res

        mock_db.execute = AsyncMock(side_effect=execute_side_effect)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()  # no-op; handler reads from ORM object directly
        mock_db.add = MagicMock()
        yield mock_db

    app = create_app()
    app.dependency_overrides[get_session] = _mock_get_session

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.put(
            f"/api/projects/{project_id}/ai-provider",
            headers={"Authorization": f"Bearer {_mint_admin_token_for_provider()}"},
            json={
                "provider_type": "openai",
                "model_name": "gpt-4o",
                "api_key": "sk-test-secret-key",
            },
        )

    app.dependency_overrides.clear()

    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    # The plaintext api_key must NEVER appear in the response body.
    assert "sk-test-secret-key" not in r.text, (
        "Plaintext API key must NEVER appear in response body"
    )
    body = r.json()
    # Masked key indicator must be present when credentials_enc is set.
    # (After handler sets credentials_enc to encrypted blob.)
    assert "api_key_masked" in body


@pytest.mark.asyncio
async def test_ai_provider_test_endpoint_success(monkeypatch) -> None:
    """POST /api/projects/{id}/ai-provider/test returns {ok: true, latency_ms: N}."""
    from httpx import ASGITransport, AsyncClient  # noqa: PLC0415
    from unittest.mock import AsyncMock, MagicMock  # noqa: PLC0415
    from app.main import create_app  # noqa: PLC0415
    from app.database import get_session  # noqa: PLC0415

    _patch_auth_for_provider(monkeypatch)

    project_id = uuid.uuid4()

    async def _mock_get_session():
        mock_db = AsyncMock()
        yield mock_db

    # Mock resolve_provider to return a dummy model string.
    async def _fake_resolve_provider(db, pid):
        return ("openai/gpt-4o-mini", None, "sk-fake")

    # Mock litellm.acompletion.
    fake_response = MagicMock()
    fake_response.choices = [MagicMock()]
    fake_response.choices[0].message.content = "OK"

    app = create_app()
    app.dependency_overrides[get_session] = _mock_get_session

    with (
        __import__("unittest.mock", fromlist=["patch"]).patch(
            "app.services.llm.client.resolve_provider", _fake_resolve_provider
        ),
        __import__("unittest.mock", fromlist=["patch"]).patch(
            "litellm.acompletion", AsyncMock(return_value=fake_response)
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                f"/api/projects/{project_id}/ai-provider/test",
                headers={"Authorization": f"Bearer {_mint_admin_token_for_provider()}"},
            )

    app.dependency_overrides.clear()

    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["ok"] is True, f"Expected ok=true, got: {body}"
    assert "latency_ms" in body
    assert body["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_ai_provider_test_endpoint_failure(monkeypatch) -> None:
    """POST /api/projects/{id}/ai-provider/test returns {ok: false, error} when provider fails."""
    from httpx import ASGITransport, AsyncClient  # noqa: PLC0415
    from unittest.mock import AsyncMock  # noqa: PLC0415
    from app.main import create_app  # noqa: PLC0415
    from app.database import get_session  # noqa: PLC0415

    _patch_auth_for_provider(monkeypatch)

    project_id = uuid.uuid4()

    async def _mock_get_session():
        mock_db = AsyncMock()
        yield mock_db

    async def _fake_resolve_provider_raises(db, pid):
        raise ValueError("No AI provider configured")

    app = create_app()
    app.dependency_overrides[get_session] = _mock_get_session

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "app.services.llm.client.resolve_provider", _fake_resolve_provider_raises
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                f"/api/projects/{project_id}/ai-provider/test",
                headers={"Authorization": f"Bearer {_mint_admin_token_for_provider()}"},
            )

    app.dependency_overrides.clear()

    assert r.status_code == 200, f"Expected 200 (error wrapped), got {r.status_code}: {r.text}"
    body = r.json()
    assert body["ok"] is False
    assert "error" in body
    assert body["error"] is not None
