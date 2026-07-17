"""Integration test stubs — actor alias fuzzy matching thresholds.

Wave 0: all tests are xfail stubs. They will go GREEN when
plan 25-04 ships the match_actor_name() service using rapidfuzz.

Coverage:
  ACTOR-04 — fuzzy alias matching:
              score >= 85  → ('auto_link', actor)
              score 60–84  → ('stage', actor)
              score < 60   → ('discard', None)
              case-insensitive match
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.xfail(strict=False, reason="implementation pending —")
async def test_auto_link_at_85():
    """match_actor_name() returns ('auto_link', actor) when fuzz score >= 85.

    Uses rapidfuzz.fuzz.token_sort_ratio threshold.
    Example: 'Cozy Bear' vs 'CozyBear' should score >= 85.
    """
    assert False, "stub — implement after match_actor_name ships"


@pytest.mark.xfail(strict=False, reason="implementation pending —")
async def test_stage_at_65():
    """match_actor_name() returns ('stage', actor) when fuzz score is in 60–84.

    Example: a partially-matching alias should land in the staging bucket
    for human review rather than auto-linking.
    """
    assert False, "stub — implement after match_actor_name ships"


@pytest.mark.xfail(strict=False, reason="implementation pending —")
async def test_discard_below_60():
    """match_actor_name() returns ('discard', None) when fuzz score < 60.

    Example: completely unrelated actor name should be discarded rather
    than staged or auto-linked.
    """
    assert False, "stub — implement after match_actor_name ships"


@pytest.mark.xfail(strict=False, reason="implementation pending —")
async def test_case_insensitive_match():
    """match_actor_name() matches 'apt29' to 'APT29' with score >= 85.

    Actor name lookup must be case-insensitive; 'apt29' and 'APT29'
    should auto-link to the same threat_actors row.
    Uses fuzz.token_sort_ratio which normalises case before scoring.
    """
    assert False, "stub — implement after match_actor_name ships"
