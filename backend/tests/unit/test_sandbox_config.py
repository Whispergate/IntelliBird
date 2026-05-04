"""
SANDBOX-01 — per-project sandbox config: encrypted API key storage, OPSEC gate.
Implemented in: backend/app/routers/projects/sandbox.py (Phase 27 Plan 04)
"""
import pytest


@pytest.mark.xfail(reason="not yet implemented — Phase 27 Plan 04")
def test_put_sandbox_config_stores_encrypted_key():
    """PUT /api/projects/{id}/sandbox-config stores API key via encrypt_credentials."""
    raise NotImplementedError


@pytest.mark.xfail(reason="not yet implemented — Phase 27 Plan 04")
def test_put_sandbox_config_opsec_gate_raises_422():
    """Public provider without public_warning_acknowledged=True raises HTTP 422."""
    raise NotImplementedError


@pytest.mark.xfail(reason="not yet implemented — Phase 27 Plan 04")
def test_put_sandbox_config_default_disabled():
    """Project with no sandbox_configs row behaves as disabled (no submission triggered)."""
    raise NotImplementedError
