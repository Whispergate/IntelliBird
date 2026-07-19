"""Fuzzy alias matching for AI-extracted actor names.

Thresholds (per 25-CONTEXT.md decision):
  score >= 85  → "auto_link"  - write actor_event_links row directly
  score 60–84  → "stage"      - create AISuggestion type='actor' for analyst review
  score < 60   → "discard"    - drop silently

Uses rapidfuzz.fuzz.token_sort_ratio - handles word-order permutations
(e.g. 'APT 29' vs 'APT29').
"""
from __future__ import annotations

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.actors import ThreatActor

_AUTO_LINK_THRESHOLD = 85
_STAGE_THRESHOLD = 60


async def match_actor_name(
    db: AsyncSession,
    name: str,
) -> tuple[str, ThreatActor | None]:
    """Return (decision, actor_or_None).

    decision is one of: 'auto_link' | 'stage' | 'discard'

    Iterates all ThreatActor rows and scores the input name against each
    actor's primary_name and aliases using rapidfuzz.fuzz.token_sort_ratio.
    The best score across all candidates determines the decision bucket.
    """
    result = await db.execute(select(ThreatActor))
    actors = result.scalars().all()

    best_score = 0
    best_actor: ThreatActor | None = None
    name_lower = name.lower()

    for actor in actors:
        candidates = [actor.primary_name] + (actor.aliases or [])
        for candidate in candidates:
            score = fuzz.token_sort_ratio(name_lower, candidate.lower())
            if score > best_score:
                best_score = score  # type: ignore[assignment]
                best_actor = actor

    if best_score >= _AUTO_LINK_THRESHOLD:
        return "auto_link", best_actor
    if best_score >= _STAGE_THRESHOLD:
        return "stage", best_actor
    return "discard", None
