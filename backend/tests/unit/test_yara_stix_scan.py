"""
YARA-03 — STIX pattern string scan: extracts indicator value; only fires on stix_pattern_scan=true rules.
Implemented in: backend/app/services/yara_engine.py (Phase 27 Plan 03) + ingest hook (Phase 27 Plan 06)
"""
import pytest


@pytest.mark.xfail(reason="not yet implemented — Phase 27 Plan 03+06")
def test_stix_pattern_extracts_sha256_from_pattern():
    """Regex extractor pulls hash value from [file:hashes.'SHA-256' = '<value>'] pattern string."""
    raise NotImplementedError


@pytest.mark.xfail(reason="not yet implemented — Phase 27 Plan 03+06")
def test_stix_scan_only_fires_on_stix_pattern_scan_rules():
    """YARA-03 scan ignores rules without stix_pattern_scan: true metadata; does not scan against them."""
    raise NotImplementedError


@pytest.mark.xfail(reason="not yet implemented — Phase 27 Plan 03+06")
def test_stix_scan_returns_empty_when_no_stix_rules_enabled():
    """When no rules have stix_pattern_scan: true, scan_stix_pattern() returns []."""
    raise NotImplementedError
