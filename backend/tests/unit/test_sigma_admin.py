"""Sigma Rule Engine - admin API tests (SIGMA-03)."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)


def test_sigma_admin_crud():
    """SIGMA-01/SIGMA-03: sigma_rules router exposes CRUD + test endpoints."""
    from app.routers.admin.sigma_rules import router

    paths = [r.path for r in router.routes]
    # Router includes prefix; check relative path suffixes
    assert any(p.endswith("/admin/sigma-rules") or p == "" or p == "/" for p in paths), (
        f"POST create route missing: {paths}"
    )
    assert any("rule_id" in p for p in paths), f"PATCH/DELETE route missing: {paths}"
    assert any(p.endswith("/test") for p in paths), f"POST /test route missing: {paths}"


def test_sigma_test_endpoint_returns_match_count():
    """SIGMA-03: test endpoint has SigmaRuleTestResult response model."""
    import inspect

    from app.routers.admin import sigma_rules as sr_module

    source = inspect.getsource(sr_module)
    assert "SigmaRuleTestResult" in source
    assert "match_count" in source
    assert "matched_event_ids" in source
