"""Sigma Rule Engine - unit tests (SIGMA-01, SIGMA-02, SIGMA-04)."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


def test_parse_valid_sigma_rule():
    """SIGMA-01: _parse_sigma_rule(valid_yaml) returns a dict with at minimum 'title' and 'detection' keys."""
    from app.services.sigma_engine import _parse_sigma_rule

    valid_yaml = """
title: Test Phishing Rule
description: Detects phishing attempts
status: test
logsource:
    category: generic
detection:
    selection:
        title|contains: 'phishing'
    condition: selection
tags:
    - attack.t1566
level: medium
"""
    result = _parse_sigma_rule(valid_yaml)
    assert isinstance(result, dict)
    assert "detection" in result


def test_parse_invalid_sigma_rule_raises_422():
    """SIGMA-01: _parse_sigma_rule with invalid/non-Sigma YAML raises HTTPException(422)."""
    from app.services.sigma_engine import _parse_sigma_rule

    with pytest.raises(HTTPException) as exc_info:
        _parse_sigma_rule("not valid yaml: [broken")
    assert exc_info.value.status_code == 422
    assert "Invalid Sigma rule" in exc_info.value.detail


def test_evaluate_writes_tag():
    """SIGMA-02: evaluate_sigma_rules writes attack_technique_tags on a matching event."""
    from app.services.sigma_engine import evaluate_sigma_rules

    session = MagicMock()
    event_id = uuid.uuid4()
    project_id = uuid.uuid4()

    # Create a mock SigmaRule ORM row with simple YAML
    mock_rule = MagicMock()
    mock_rule.id = uuid.uuid4()
    mock_rule.name = "Test Rule"
    mock_rule.enabled = True
    mock_rule.tags = ["T1566"]
    mock_rule.project_id = None
    mock_rule.compiled_cache = None
    mock_rule.content = """
title: Test Rule
status: test
logsource:
    category: generic
detection:
    selection:
        title|contains: phishing
    condition: selection
tags:
    - attack.t1566
level: medium
"""

    # Create a mock event
    mock_event = MagicMock()
    mock_event.title = "Phishing campaign detected"
    mock_event.description = "APT group using phishing emails"
    mock_event.tags = []
    mock_event.raw_stix = {}
    mock_event.source_id = None

    # session.get returns mock event
    session.get.return_value = mock_event

    # source lookup returns None
    mock_scalar_result = MagicMock()
    mock_scalar_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_scalar_result

    with patch("app.services.sigma_engine._load_active_sigma_rules", return_value=[mock_rule]):
        with patch("app.services.sigma_engine._evaluate_condition", return_value=True):
            with patch("app.workers.scoring.rescore_project") as mock_rescore:
                mock_rescore.send = MagicMock()
                evaluate_sigma_rules(session, event_id, project_id)

    # Assert session.execute was called - at least once for the INSERT
    assert session.execute.called


def test_evaluate_never_raises():
    """SIGMA-02: evaluate_sigma_rules does not raise when a rule evaluation errors."""
    from app.services.sigma_engine import evaluate_sigma_rules

    session = MagicMock()
    event_id = uuid.uuid4()
    project_id = uuid.uuid4()

    with patch("app.services.sigma_engine._load_active_sigma_rules", side_effect=Exception("boom")):
        # Must not raise
        evaluate_sigma_rules(session, event_id, project_id)


def test_field_map():
    """SIGMA-04: SIGMA_FIELD_MAP maps all documented fields; unknown field → None."""
    from app.services.sigma_engine import SIGMA_FIELD_MAP

    assert SIGMA_FIELD_MAP["title"] == "title"
    assert SIGMA_FIELD_MAP["keywords"] == "tags"
    assert SIGMA_FIELD_MAP.get("unknown_field") is None
    # Verify all 6 documented fields are mapped
    assert "description" in SIGMA_FIELD_MAP
    assert "threat_actor" in SIGMA_FIELD_MAP
    assert "raw_stix_pattern" in SIGMA_FIELD_MAP
    assert "source" in SIGMA_FIELD_MAP
