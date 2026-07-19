"""
MISP-01 - Admin configures MISP URL + API key per project via misp_configs table.
          Credential stored encrypted via app.crypto.encrypt_credentials.

Implemented in: backend/app/routers/misp.py
"""
import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)


@pytest.mark.xfail(reason="misp_configs table/router not yet implemented", strict=False)
def test_misp_config_credential_encrypt_roundtrip():
    """API key encrypted with encrypt_credentials and decrypted correctly."""
    from app.crypto import encrypt_credentials, decrypt_credentials
    secret = "a" * 32
    enc = encrypt_credentials(secret, {"api_key": "test-key-123"})
    dec = decrypt_credentials(secret, enc)
    assert dec["api_key"] == "test-key-123"


@pytest.mark.xfail(reason="MispConfig ORM not yet implemented", strict=False)
def test_misp_config_model_has_required_columns():
    """MispConfig ORM model has all required columns per CONTEXT.md schema."""
    from app.models.misp import MispConfig
    cols = {c.key for c in MispConfig.__table__.columns}
    required = {"id", "project_id", "url", "api_key_enc", "pull_tags",
                "push_types", "enabled", "ssl_verify", "created_at", "updated_at"}
    assert required <= cols


@pytest.mark.xfail(reason="MISP router not yet implemented", strict=False)
def test_misp_config_project_unique_constraint():
    """misp_configs has UNIQUE constraint on project_id (one MISP per project)."""
    from app.models.misp import MispConfig
    uniqs = [c for c in MispConfig.__table__.constraints
             if hasattr(c, "columns") and "project_id" in [x.key for x in c.columns]]
    assert any(type(u).__name__ in ("UniqueConstraint",) for u in uniqs)
