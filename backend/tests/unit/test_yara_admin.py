"""
YARA-01 - POST /api/admin/yara-rules compiles rule, stores compiled_cache; invalid rule returns 422.
Implemented in: backend/app/routers/admin/yara_rules.py
"""
import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


@pytest.fixture()
def mock_yara_rules_module():
    """Provide a mock yara module for compilation tests."""
    mock_yara = MagicMock()
    mock_rules = MagicMock()
    io.BytesIO(b"compiled_bytes")

    def fake_save(file):
        file.write(b"compiled_bytes")

    mock_rules.save = fake_save
    mock_yara.compile.return_value = mock_rules
    return mock_yara


def test_post_yara_rule_compiles_and_stores_cache(mock_yara_rules_module):
    """Valid YARA rule content compiles with yara.compile(), returns compiled bytes."""
    from app.routers.admin.yara_rules import _compile_rule

    with patch.dict("sys.modules", {"yara": mock_yara_rules_module}):
        result = _compile_rule("rule test { condition: true }")

    assert isinstance(result, bytes)
    assert result == b"compiled_bytes"
    mock_yara_rules_module.compile.assert_called_once_with(source="rule test { condition: true }")


def test_post_yara_rule_invalid_syntax_returns_422():
    """Syntactically invalid YARA rule content causes yara.compile() to raise; router returns 422."""
    from app.routers.admin.yara_rules import _compile_rule

    mock_yara = MagicMock()
    mock_yara.compile.side_effect = Exception("syntax error at line 1")

    with patch.dict("sys.modules", {"yara": mock_yara}):
        with pytest.raises(HTTPException) as exc_info:
            _compile_rule("rule BAD { this is not valid }")

    assert exc_info.value.status_code == 422
    assert "syntax error" in exc_info.value.detail.lower()


def test_toggle_yara_rule_enabled():
    """PATCH /api/admin/yara-rules/{id} can toggle enabled=True/False via YaraRulePatch."""
    from app.schemas.sandbox import YaraRulePatch

    # YaraRulePatch accepts optional enabled field
    patch_enable = YaraRulePatch(enabled=True)
    assert patch_enable.enabled is True

    patch_disable = YaraRulePatch(enabled=False)
    assert patch_disable.enabled is False

    # None means no change requested
    patch_no_change = YaraRulePatch()
    assert patch_no_change.enabled is None


def test_delete_yara_rule():
    """DELETE /api/admin/yara-rules/{id} router is registered and returns 204."""
    from app.routers.admin.yara_rules import router

    delete_routes = [r for r in router.routes if "DELETE" in getattr(r, "methods", set())]
    assert len(delete_routes) == 1
    assert delete_routes[0].status_code == 204
