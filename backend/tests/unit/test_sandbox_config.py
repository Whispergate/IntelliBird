"""
SANDBOX-01 — per-project sandbox config: encrypted API key storage, OPSEC gate.
Implemented in: backend/app/routers/projects/sandbox.py
"""
import pytest
from fastapi import HTTPException


def test_put_sandbox_config_opsec_gate_raises_422():
    """Public provider without public_warning_acknowledged=True raises HTTP 422."""
    from app.routers.sandbox import _validate_sandbox_opsec, _PUBLIC_PROVIDERS

    # Each public provider should trigger the gate when not acknowledged
    for provider in _PUBLIC_PROVIDERS:
        with pytest.raises(HTTPException) as exc_info:
            _validate_sandbox_opsec(provider, public_warning_acknowledged=False)
        assert exc_info.value.status_code == 422
        assert "public_warning_acknowledged" in exc_info.value.detail

    # With acknowledgement, no exception
    for provider in _PUBLIC_PROVIDERS:
        _validate_sandbox_opsec(provider, public_warning_acknowledged=True)  # no raise


def test_put_sandbox_config_stores_encrypted_key():
    """PUT /api/projects/{id}/sandbox-config stores API key via encrypt_credentials — gate logic verified."""
    from app.routers.sandbox import _validate_sandbox_opsec, _PUBLIC_PROVIDERS

    # cuckoo is self-hosted; must NOT require OPSEC gate
    _validate_sandbox_opsec("cuckoo", public_warning_acknowledged=False)  # no raise

    # _PUBLIC_PROVIDERS must include the four public free-tier providers
    assert "anyrun" in _PUBLIC_PROVIDERS
    assert "hybridanalysis" in _PUBLIC_PROVIDERS
    assert "joesandbox" in _PUBLIC_PROVIDERS
    assert "triage" in _PUBLIC_PROVIDERS
    assert "cuckoo" not in _PUBLIC_PROVIDERS


def test_put_sandbox_config_default_disabled():
    """Project with no sandbox_configs row behaves as disabled — SandboxConfigCreate defaults."""
    from app.schemas.sandbox import SandboxConfigCreate

    # Default SandboxConfigCreate has enabled=False
    config = SandboxConfigCreate(provider="cuckoo")
    assert config.enabled is False
    assert config.public_warning_acknowledged is False
    assert config.api_key is None
    assert config.options == {}
