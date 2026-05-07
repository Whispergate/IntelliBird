"""RED tests for AI attack path analysis — Pydantic schemas and parse helper.

Plan 35-01 (TDD RED phase): These tests define the interface contract for
AttackPathNode, AttackPathEdge, AttackPathRequest, AttackPathResponse schemas
and the parse_attack_path_response helper.

These tests MUST FAIL before Plan 35-02 implements the schemas and helper.
They will be made GREEN in Plan 35-02/35-03.
"""
import json
import os

import pytest
from pydantic import ValidationError

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

from app.schemas.ai import (  # noqa: E402
    AttackPathEdge,
    AttackPathNode,
    AttackPathRequest,
    AttackPathResponse,
)
from app.services.llm.attack_path import parse_attack_path_response  # noqa: E402

# ---------------------------------------------------------------------------
# Sample data for tests
# ---------------------------------------------------------------------------

VALID_NODE = {
    "id": "step_1",
    "technique_id": "T1566.001",
    "tactic": "initial-access",
    "name": "Spearphishing Attachment",
    "confidence": 0.9,
    "rationale": "Email with malicious attachment observed in threat intel feed.",
}

VALID_RESPONSE = {
    "nodes": [
        {
            "id": "step_1",
            "technique_id": "T1566.001",
            "tactic": "initial-access",
            "name": "Spearphishing",
            "confidence": 0.9,
            "rationale": "Email observed.",
        },
    ],
    "edges": [{"from": "step_1", "to": "step_1", "rationale": "self-ref test"}],
    "truncated": False,
    "model_used": "openai/gpt-4o",
    "events_analysed": 5,
}


# ---------------------------------------------------------------------------
# AttackPathNode tests
# ---------------------------------------------------------------------------


def test_attack_path_node_accepts_valid_sub_technique():
    """AttackPathNode accepts technique_id='T1566.001' (sub-technique format)."""
    node = AttackPathNode(**VALID_NODE)
    assert node.technique_id == "T1566.001"


def test_attack_path_node_accepts_base_technique_id():
    """AttackPathNode accepts technique_id='T1059' (no sub-technique)."""
    data = {**VALID_NODE, "technique_id": "T1059"}
    node = AttackPathNode(**data)
    assert node.technique_id == "T1059"


def test_attack_path_node_rejects_invalid_technique_id():
    """AttackPathNode rejects technique_id='INVALID' with ValidationError."""
    data = {**VALID_NODE, "technique_id": "INVALID"}
    with pytest.raises(ValidationError):
        AttackPathNode(**data)


def test_attack_path_node_rejects_lowercase_technique_id():
    """AttackPathNode rejects lowercase technique_id like 't1566' (must be uppercase T)."""
    data = {**VALID_NODE, "technique_id": "t1566"}
    with pytest.raises(ValidationError):
        AttackPathNode(**data)


def test_attack_path_node_rejects_confidence_above_one():
    """AttackPathNode rejects confidence > 1.0."""
    data = {**VALID_NODE, "confidence": 1.5}
    with pytest.raises(ValidationError):
        AttackPathNode(**data)


def test_attack_path_node_rejects_confidence_below_zero():
    """AttackPathNode rejects confidence < 0.0."""
    data = {**VALID_NODE, "confidence": -0.1}
    with pytest.raises(ValidationError):
        AttackPathNode(**data)


# ---------------------------------------------------------------------------
# AttackPathEdge tests
# ---------------------------------------------------------------------------


def test_attack_path_edge_maps_from_alias():
    """AttackPathEdge maps JSON 'from' key to Python attribute correctly."""
    edge_data = {"from": "step_1", "to": "step_2", "rationale": "pivot"}
    edge = AttackPathEdge.model_validate(edge_data)
    # The Python attribute should be accessible (either as from_ or via alias)
    assert edge.to == "step_2"
    assert edge.rationale == "pivot"
    # Verify 'from' field value is accessible
    edge_dict = edge.model_dump(by_alias=True)
    assert edge_dict.get("from") == "step_1"


# ---------------------------------------------------------------------------
# AttackPathResponse tests
# ---------------------------------------------------------------------------


def test_attack_path_response_accepts_valid_full_response():
    """AttackPathResponse accepts a complete valid response dict."""
    response = AttackPathResponse(**VALID_RESPONSE)
    assert len(response.nodes) == 1
    assert len(response.edges) == 1
    assert response.truncated is False
    assert response.model_used == "openai/gpt-4o"
    assert response.events_analysed == 5


def test_attack_path_response_accepts_empty_nodes_and_edges():
    """AttackPathResponse with empty nodes/edges lists is valid."""
    data = {
        "nodes": [],
        "edges": [],
        "truncated": False,
        "model_used": "openai/gpt-4o",
        "events_analysed": 0,
    }
    response = AttackPathResponse(**data)
    assert response.nodes == []
    assert response.edges == []


# ---------------------------------------------------------------------------
# AttackPathRequest tests
# ---------------------------------------------------------------------------


def test_attack_path_request_defaults_days_to_30():
    """AttackPathRequest defaults days=30 when not provided."""
    req = AttackPathRequest()
    assert req.days == 30


def test_attack_path_request_rejects_days_above_90():
    """AttackPathRequest rejects days=91 (max is 90)."""
    with pytest.raises(ValidationError):
        AttackPathRequest(days=91)


def test_attack_path_request_rejects_days_zero():
    """AttackPathRequest rejects days=0 (min is 1)."""
    with pytest.raises(ValidationError):
        AttackPathRequest(days=0)


def test_attack_path_request_accepts_days_1():
    """AttackPathRequest accepts days=1 (minimum boundary)."""
    req = AttackPathRequest(days=1)
    assert req.days == 1


def test_attack_path_request_accepts_days_90():
    """AttackPathRequest accepts days=90 (maximum boundary)."""
    req = AttackPathRequest(days=90)
    assert req.days == 90


# ---------------------------------------------------------------------------
# parse_attack_path_response tests
# ---------------------------------------------------------------------------


def test_parse_attack_path_response_returns_response_for_valid_json():
    """parse_attack_path_response returns AttackPathResponse for valid JSON string."""
    json_str = json.dumps(VALID_RESPONSE)
    result = parse_attack_path_response(json_str)
    assert isinstance(result, AttackPathResponse)
    assert len(result.nodes) == 1


def test_parse_attack_path_response_raises_value_error_for_invalid_json():
    """parse_attack_path_response raises ValueError for invalid JSON."""
    with pytest.raises(ValueError):
        parse_attack_path_response("this is not json {{{")


def test_parse_attack_path_response_strips_json_fences():
    """parse_attack_path_response strips ```json ... ``` markdown fences before parsing."""
    json_str = json.dumps(VALID_RESPONSE)
    fenced = f"```json\n{json_str}\n```"
    result = parse_attack_path_response(fenced)
    assert isinstance(result, AttackPathResponse)
    assert len(result.nodes) == 1
