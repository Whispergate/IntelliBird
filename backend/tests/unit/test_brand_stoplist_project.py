"""Unit tests for load_runtime_stoplist_for_project — Phase 21 / BRAND-01.

Tests the additive union behaviour of the new async per-project stoplist loader.
All three tests should FAIL at RED phase (function does not exist yet).
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("SECRET_KEY", "x" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "y" * 64)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_async_session(term_rows: list[str]):
    """Build a minimal AsyncSession stub that returns `term_rows` from scalars()."""
    scalars_result = MagicMock()
    scalars_result.all.return_value = term_rows

    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_result

    session = AsyncMock()
    session.execute = AsyncMock(return_value=execute_result)
    return session


# ---------------------------------------------------------------------------
# Test 1 — returns DEFAULT ∪ env-extra ∪ project terms
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_runtime_stoplist_for_project_returns_union():
    """await load_runtime_stoplist_for_project(session, project_id) returns
    DEFAULT_STOPLIST ∪ BRAND_STOPLIST_EXTRA env terms ∪ project terms.
    """
    from app.services.brand_stoplist import (
        DEFAULT_STOPLIST,
        load_runtime_stoplist_for_project,
    )

    project_id = uuid.uuid4()
    project_terms = ["noise.example", "CustomBrand"]
    session = _make_async_session(project_terms)

    result = await load_runtime_stoplist_for_project(session, project_id)

    # Must be a frozenset
    assert isinstance(result, frozenset)

    # All DEFAULT entries present
    assert "apex" in result  # sample DEFAULT_STOPLIST entry

    # Project term (lowercased) present
    assert "noise.example" in result
    assert "custombrand" in result  # stored as "CustomBrand", lowercased

    # Superset of the zero-arg result
    from app.services.brand_stoplist import load_runtime_stoplist
    assert load_runtime_stoplist().issubset(result)


# ---------------------------------------------------------------------------
# Test 2 — project with no terms == zero-arg result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_runtime_stoplist_for_project_empty_project_equals_global():
    """Project with no stoplist terms returns same frozenset as zero-arg load_runtime_stoplist()."""
    from app.services.brand_stoplist import (
        load_runtime_stoplist,
        load_runtime_stoplist_for_project,
    )

    project_id = uuid.uuid4()
    session = _make_async_session([])  # no project terms

    result = await load_runtime_stoplist_for_project(session, project_id)
    global_result = load_runtime_stoplist()

    assert result == global_result


# ---------------------------------------------------------------------------
# Test 3 — project term casing: stored as-typed, membership check via lower()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_runtime_stoplist_for_project_lowercases_terms():
    """Terms stored as mixed-case are lowercased into the returned frozenset
    so consumers can check membership with lower() as they do for DEFAULT entries.
    """
    from app.services.brand_stoplist import load_runtime_stoplist_for_project

    project_id = uuid.uuid4()
    # Stored as mixed-case (as operator typed them)
    session = _make_async_session(["AcmeCorp", "NOISE.IO", "MixedCase"])

    result = await load_runtime_stoplist_for_project(session, project_id)

    # All must be present as lowercased
    assert "acmecorp" in result
    assert "noise.io" in result
    assert "mixedcase" in result

    # Original mixed-case strings must NOT appear as-is
    assert "AcmeCorp" not in result
    assert "NOISE.IO" not in result
