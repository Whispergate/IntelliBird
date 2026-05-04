"""Phase 29 Sigma Rule Engine — admin API tests (SIGMA-03)."""
import pytest


@pytest.mark.skip(reason="Wave 0 stub — implemented in 29-05")
def test_sigma_admin_crud():
    """SIGMA-03: admin CRUD endpoints (POST/GET/PUT/DELETE /api/admin/sigma-rules) exist and return expected status codes."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — implemented in 29-05")
def test_sigma_test_endpoint_returns_match_count():
    """SIGMA-03: POST /api/admin/sigma-rules/test returns {match_count, matched_event_ids} for a known-matching rule."""
    pass
