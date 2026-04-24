"""Tests for app.services.brand_severity.score — pure function truth table.

Activated by plan 12-02 (Wave 2 service primitives).
"""
from __future__ import annotations

import os

# Pydantic-settings singleton is loaded at import time; inject required env vars
# before any app.* import to prevent ValidationError at collection time.
os.environ.setdefault("SECRET_KEY", "x" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "y" * 64)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest

from app.services.brand_severity import score


def test_fts_returns_low():
    assert score(match_source="fts", dnstwist_success=False) == "low"


def test_fts_with_success_irrelevant_returns_low():
    # FTS ignores the dnstwist_success flag — FTS hits are always low.
    assert score(match_source="fts", dnstwist_success=True) == "low"


def test_ct_log_returns_medium():
    assert score(match_source="ct_log", dnstwist_success=False) == "medium"


def test_ct_log_with_success_true_still_medium():
    assert score(match_source="ct_log", dnstwist_success=True) == "medium"


def test_dnstwist_success_returns_high():
    assert score(match_source="dnstwist", dnstwist_success=True) == "high"


def test_dnstwist_failure_returns_low():
    assert score(match_source="dnstwist", dnstwist_success=False) == "low"


def test_unknown_source_raises():
    with pytest.raises(ValueError):
        score(match_source="unknown", dnstwist_success=True)  # type: ignore[arg-type]
