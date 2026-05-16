"""
CERT-03 — When certstream_enabled=True for a project, brand_monitor_tick_job
          skips the crt.sh CT-log branch for that project (dnstwist still runs).

Implemented in: backend/app/services/brand_monitor.py (Phase 32 Plan 03)
"""
import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)


@pytest.mark.xfail(reason="certstream_enabled guard not yet implemented", strict=False)
def test_ctlog_scan_skipped_when_certstream_enabled():
    """scan_project skips _ctlog_scan when project has certstream_enabled=True."""
    from unittest.mock import AsyncMock, patch
    from app.services.brand_monitor import scan_project
    # When certstream_enabled=True, _ctlog_scan must not be called
    # Full implementation tested in Wave 2 (Plan 03)
    assert True  # placeholder — implementation will replace


@pytest.mark.xfail(reason="certstream_enabled guard not yet implemented", strict=False)
def test_ctlog_scan_runs_when_certstream_disabled():
    """scan_project runs _ctlog_scan when certstream_enabled=False (default)."""
    assert True  # placeholder


@pytest.mark.xfail(reason="certstream_enabled guard not yet implemented", strict=False)
def test_certstream_enabled_column_default_false():
    """projects.certstream_enabled has server default FALSE."""
    from app.models.projects import Project
    col = Project.__table__.c.get("certstream_enabled")
    assert col is not None
    assert str(col.server_default.arg).lower() in ("false", "'false'")
