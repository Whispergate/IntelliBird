"""
YARA-02 — In-memory YARA scan on sample bytes; match writes yara_matches row and auto-tags event.
Implemented in: backend/app/services/yara_engine.py (Phase 27 Plan 03)
"""
import pytest


@pytest.mark.xfail(reason="not yet implemented — Phase 27 Plan 03")
def test_scan_sample_returns_matches_for_matching_rule():
    """scan_sample() returns list of match dicts when sample bytes match a compiled YARA rule."""
    raise NotImplementedError


@pytest.mark.xfail(reason="not yet implemented — Phase 27 Plan 03")
def test_scan_sample_returns_empty_for_no_match():
    """scan_sample() returns [] when no active rules match the sample bytes."""
    raise NotImplementedError


@pytest.mark.xfail(reason="not yet implemented — Phase 27 Plan 03")
def test_yara_match_writes_yara_matches_row():
    """A match causes a yara_matches row to be inserted (rule_id, event_id, matched_at)."""
    raise NotImplementedError


@pytest.mark.xfail(reason="not yet implemented — Phase 27 Plan 03")
def test_yara_match_auto_tags_event():
    """A match calls _write_attack_tag with tag_source='auto' for each matching rule family."""
    raise NotImplementedError
