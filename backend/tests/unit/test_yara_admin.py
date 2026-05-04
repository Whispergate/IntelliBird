"""
YARA-01 — POST /api/admin/yara-rules compiles rule, stores compiled_cache; invalid rule returns 422.
Implemented in: backend/app/routers/admin/yara_rules.py (Phase 27 Plan 04)
"""
import pytest


@pytest.mark.xfail(reason="not yet implemented — Phase 27 Plan 04")
def test_post_yara_rule_compiles_and_stores_cache():
    """Valid .yar file upload compiles with yara.compile(), stores compiled_cache bytes."""
    raise NotImplementedError


@pytest.mark.xfail(reason="not yet implemented — Phase 27 Plan 04")
def test_post_yara_rule_invalid_syntax_returns_422():
    """Syntactically invalid YARA rule content causes yara.compile() to raise; router returns 422."""
    raise NotImplementedError


@pytest.mark.xfail(reason="not yet implemented — Phase 27 Plan 04")
def test_toggle_yara_rule_enabled():
    """PATCH /api/admin/yara-rules/{id} can toggle enabled=True/False."""
    raise NotImplementedError


@pytest.mark.xfail(reason="not yet implemented — Phase 27 Plan 04")
def test_delete_yara_rule():
    """DELETE /api/admin/yara-rules/{id} removes the rule row."""
    raise NotImplementedError
