"""Phase 29 Sigma Rule Engine — integration tests (SIGMA-01, SIGMA-02, SIGMA-03)."""
import pytest


@pytest.mark.integration
@pytest.mark.skip(reason="Wave 0 stub — implemented in 29-04/29-05")
def test_sigma_rule_stored_in_db():
    """SIGMA-01: ORM model for sigma_rules table saves and retrieves a rule from DB correctly."""
    pass


@pytest.mark.integration
@pytest.mark.skip(reason="Wave 0 stub — implemented in 29-04/29-05")
def test_ingest_hook_writes_attack_tag():
    """SIGMA-02: evaluate_sigma_rules called in _persist_event writes attack_technique_tags on a matching event."""
    pass


@pytest.mark.integration
@pytest.mark.skip(reason="Wave 0 stub — implemented in 29-04/29-05")
def test_test_endpoint_returns_match_count():
    """SIGMA-03: POST /api/admin/sigma-rules/test returns {match_count, matched_event_ids} for a known-matching rule."""
    pass
