"""
CERT-01 - certstream_worker connects to wss://certstream.calidog.io and filters
          domains against project brand_terms patterns.
CERT-02 - Matching CT log entries persist as brand-monitor events with
          match_source='certstream' tag.

Implemented in: backend/app/workers/certstream_worker.py
"""
import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)


@pytest.mark.xfail(reason="certstream_worker not yet implemented", strict=False)
def test_frame_parsing_extracts_all_domains():
    """CertStream JSON frame: all_domains list is extracted from data.leaf_cert."""
    from app.workers.certstream_worker import _extract_domains
    frame = {
        "message_type": "certificate_update",
        "data": {"leaf_cert": {"all_domains": ["example.com", "www.example.com"]}},
    }
    assert _extract_domains(frame) == ["example.com", "www.example.com"]


@pytest.mark.xfail(reason="certstream_worker not yet implemented", strict=False)
def test_frame_parsing_ignores_non_update_messages():
    """Heartbeat frames (message_type != certificate_update) return empty list."""
    from app.workers.certstream_worker import _extract_domains
    frame = {"message_type": "heartbeat", "data": {}}
    assert _extract_domains(frame) == []


@pytest.mark.xfail(reason="certstream_worker not yet implemented", strict=False)
def test_pattern_match_suffix():
    """Domain suffix matching: 'login.evil-example.com' matches pattern 'example'."""
    from app.workers.certstream_worker import _matches_pattern
    assert _matches_pattern("login.evil-example.com", "example") is True
    assert _matches_pattern("unrelated.com", "example") is False


@pytest.mark.xfail(reason="certstream_worker not yet implemented", strict=False)
def test_match_source_is_certstream():
    """Persisted BrandMatch row has match_source='certstream' (CERT-02)."""
    from app.workers.certstream_worker import _build_match_dict
    m = _build_match_dict(domain="login.evil.com", pattern="evil", project_id="proj-1")
    assert m["match_source"] == "certstream"
