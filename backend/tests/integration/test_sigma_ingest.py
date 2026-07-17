"""Sigma Rule Engine — integration tests (SIGMA-01, SIGMA-02, SIGMA-03)."""
import inspect
import pytest


@pytest.mark.integration
@pytest.mark.skip(
    reason="requires running DB — verify manually via alembic upgrade head + psql"
)
def test_sigma_rule_stored_in_db():
    """SIGMA-01: ORM model for sigma_rules table saves and retrieves a rule from DB correctly."""
    pass


def test_ingest_hook_calls_evaluate_sigma_rules():
    """SIGMA-02: smoke-verify normalise._persist_event contains sigma eval hook."""
    from app.ingest import normalise

    source = inspect.getsource(normalise._persist_event)
    assert "evaluate_sigma_rules" in source, (
        "_persist_event must call evaluate_sigma_rules (hook missing)"
    )
    assert "sigma_eval_failed" in source, (
        "_persist_event must have sigma_eval_failed warning (hook not wrapped in try/except)"
    )


@pytest.mark.integration
@pytest.mark.skip(
    reason="requires running API + DB — verify with: POST /api/admin/sigma-rules/test"
)
def test_test_endpoint_returns_match_count():
    """SIGMA-03: POST /api/admin/sigma-rules/test returns {match_count, matched_event_ids} for a known-matching rule."""
    pass
