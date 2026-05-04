"""Phase 29 Sigma Rule Engine — unit tests (SIGMA-01, SIGMA-02, SIGMA-04)."""
import pytest


@pytest.mark.skip(reason="Wave 0 stub — implemented in 29-03")
def test_parse_valid_sigma_rule():
    """SIGMA-01: _parse_sigma_rule(valid_yaml) returns a dict with at minimum 'title' and 'detection' keys."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — implemented in 29-03")
def test_parse_invalid_sigma_rule_raises_422():
    """SIGMA-01: _parse_sigma_rule with invalid/non-Sigma YAML raises HTTPException(422)."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — implemented in 29-03")
def test_evaluate_writes_tag():
    """SIGMA-02: evaluate_sigma_rules writes attack_technique_tags on a matching event."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — implemented in 29-03")
def test_evaluate_never_raises():
    """SIGMA-02: evaluate_sigma_rules does not raise when a rule evaluation errors."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — implemented in 29-03")
def test_field_map():
    """SIGMA-04: SIGMA_FIELD_MAP maps all documented fields; unknown field → None."""
    pass
