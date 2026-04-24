"""Tests for app.services.brand_stoplist — DEFAULT_STOPLIST + env extras union + case-insensitive check.

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

from app.services.brand_stoplist import (
    DEFAULT_STOPLIST,
    is_short,
    is_stoplisted,
    load_runtime_stoplist,
)


def test_is_stoplisted_returns_true_for_default_entry():
    # "apex" is in DEFAULT_STOPLIST (generic brand word)
    assert is_stoplisted("apex") is True


def test_is_stoplisted_case_insensitive():
    assert is_stoplisted("APEX") is True
    assert is_stoplisted("ApEx") is True


def test_is_stoplisted_returns_false_for_unique_brand():
    assert is_stoplisted("intellibird") is False


def test_load_runtime_stoplist_unions_env_extra(monkeypatch):
    from app.services import brand_stoplist as mod

    class _S:
        BRAND_STOPLIST_EXTRA = "acme,coyote"

    monkeypatch.setattr(mod, "settings", _S())
    runtime = load_runtime_stoplist()
    assert "acme" in runtime
    assert "coyote" in runtime
    # DEFAULT entries are still there
    assert "apex" in runtime


def test_load_runtime_stoplist_env_extra_is_case_insensitive(monkeypatch):
    from app.services import brand_stoplist as mod

    class _S:
        BRAND_STOPLIST_EXTRA = "ACME, Coyote"

    monkeypatch.setattr(mod, "settings", _S())
    runtime = load_runtime_stoplist()
    assert "acme" in runtime
    assert "coyote" in runtime


def test_load_runtime_stoplist_handles_empty_extra(monkeypatch):
    from app.services import brand_stoplist as mod

    class _S:
        BRAND_STOPLIST_EXTRA = None

    monkeypatch.setattr(mod, "settings", _S())
    runtime = load_runtime_stoplist()
    assert runtime == DEFAULT_STOPLIST


def test_is_short_returns_true_under_6():
    assert is_short("hi") is True
    assert is_short("hello") is True
    assert is_short("hellos") is False
    assert is_short("intellibird") is False


def test_default_stoplist_is_frozenset():
    assert isinstance(DEFAULT_STOPLIST, frozenset)


def test_default_stoplist_min_size():
    # Per plan must_haves: DEFAULT_STOPLIST has ~150 entries (>=100 lower bound)
    assert len(DEFAULT_STOPLIST) >= 100


def test_default_stoplist_entries_lowercase():
    for entry in DEFAULT_STOPLIST:
        assert entry == entry.lower(), f"stoplist entry must be lowercase: {entry!r}"
