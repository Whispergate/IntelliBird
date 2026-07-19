"""Suggestion validator gate - AI-03, updated ACTOR-04.

Every LLM-extracted CVE / ATT&CK technique / actor name passes validation:
  - CVE / ATT&CK: format regex + catalog presence check (bool path)
  - Actor names: rapidfuzz fuzzy alias match against threat_actors table

The actor branch uses match_actor_name() with three outcomes:
  score >= 85  → "auto_link"  - write ActorEventLink directly (no ai_suggestion)
  score 60–84  → "stage"      - create AISuggestion type='actor' for analyst review
  score < 60   → "discard"    - drop silently

Both CVE/ATT&CK checks must pass for a suggestion to be staged. Failures are
logged at INFO and silently dropped - they never reach the ai_suggestions table.

This enforces C-2 (analyst confirmation queue must be signal-rich) and
prevents unvalidated entity rows from polluting downstream analysis.

Exports
-------
CVE_REGEX
    Compiled regex for CVE ID format validation.
ATTCK_REGEX
    Compiled regex for ATT&CK technique ID format validation.
validate_cve(db, value) -> bool
validate_attack_technique(db, value) -> bool
validate_actor_name(db, value) -> bool  [legacy; replaced by match_actor_name branch]
validate_and_stage_suggestions(db, *, ai_summary_id, project_id, event_id, candidates) -> list[AISuggestion]
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.ai import AISuggestion
from app.services.actor_alias_matcher import match_actor_name

if TYPE_CHECKING:
    from collections.abc import Sequence
    import uuid
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compiled regexes (exported for tests + callers)
# ---------------------------------------------------------------------------

CVE_REGEX = re.compile(r"^CVE-\d{4}-\d{4,7}$")
ATTCK_REGEX = re.compile(r"^T\d{4}(\.\d{3})?$")


# ---------------------------------------------------------------------------
# Individual validators
# ---------------------------------------------------------------------------

async def validate_cve(db: "AsyncSession", value: str) -> bool:
    """Return True if *value* matches CVE_REGEX AND exists in cve_details cache.

    Both checks must pass.  A well-formed CVE ID that is not yet in the local
    NVD cache fails - the operator can trigger an NVD re-ingest and
    re-summarise when needed.
    """
    if not CVE_REGEX.match(value):
        return False

    from app.models.cve_details import CveDetails  # noqa: PLC0415 - deferred import

    row = (
        await db.execute(
            select(CveDetails).where(CveDetails.cve_id == value).limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def validate_attack_technique(db: "AsyncSession", value: str) -> bool:
    """Return True if *value* matches ATTCK_REGEX AND exists in attack_techniques.

    Both checks must pass.  A well-formed technique ID absent from the local
    ATT&CK bootstrap table fails - the operator can re-run the ATT&CK bootstrap
    job to pick up newly published techniques.
    """
    if not ATTCK_REGEX.match(value):
        return False

    from app.models.attack import AttackTechnique  # noqa: PLC0415 - deferred import

    row = (
        await db.execute(
            select(AttackTechnique)
            .where(AttackTechnique.technique_id == value)
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def validate_actor_name(db: "AsyncSession", value: str) -> bool:
    """Return True if *value* matches an existing threat-actor Event row by title.

    STIX SDOs ingested from TAXII / STIX feeds are stored in the events table
    with stix_type='threat-actor' and their STIX name field mapped to
    events.title (see app.ingest.taxii_parser._title_for).

    This is intentionally STRICT - names with no matching SDO are rejected.
    The operator can manually create the SDO (or trigger a TAXII re-ingest)
    and re-summarise when needed.  This choice is deliberate per 17-CONTEXT.md
    §Suggestion validation (C-2 mitigation).
    """
    from app.models.events import Event  # noqa: PLC0415 - deferred import

    row = (
        await db.execute(
            select(Event)
            .where(Event.stix_type == "threat-actor", Event.title == value)
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

async def validate_narrative_op(db: "AsyncSession", value: str) -> bool:
    """narrative_op values are free-form JSON metadata - structural validation only.

    The AI pipeline stores the raw LLM JSON in suggestion.value. Format:
    {"claim": "...", "amplifier": "...", "audience": "...", "is_narrative_op": true}
    No catalog lookup required - always passes validator stage.
    """
    return True


VALIDATORS = {
    "cve": validate_cve,
    "attack": validate_attack_technique,
    "actor": validate_actor_name,
    "narrative_op": validate_narrative_op,
}


# ---------------------------------------------------------------------------
# Composite stager
# ---------------------------------------------------------------------------

async def validate_and_stage_suggestions(
    db: "AsyncSession",
    *,
    ai_summary_id: "uuid.UUID",
    project_id: "uuid.UUID",
    event_id: "uuid.UUID | None",
    candidates: "Sequence[tuple[str, str]]",
) -> "list[AISuggestion]":
    """Validate each candidate and insert passing rows into ai_suggestions.

    Parameters
    ----------
    db:
        Active SQLAlchemy async session. The caller is responsible for
        committing (or rolling back) after this function returns.
    ai_summary_id:
        FK to the ai_summaries row that generated these candidates.
    project_id:
        Project scope FK - stored directly on each suggestion row so the
        project-wide queue page can filter without joining through ai_summaries.
    event_id:
        Soft FK to events.id (no DB constraint - events is a hypertable).
        Pass None for digest-level suggestions (not currently used but included
        for forward compatibility).
    candidates:
        Sequence of ``(suggestion_type, value)`` tuples where ``suggestion_type``
        is one of ``"cve"``, ``"attack"``, or ``"actor"``.

    Returns
    -------
    list[AISuggestion]
        The AISuggestion rows that passed validation and were added to the
        session (not yet committed).  Invalid entries are logged and dropped.
    """
    staged: list[AISuggestion] = []

    for stype, value in candidates:
        # ── Actor branch: fuzzy alias matching (ACTOR-04) ──────────
        if stype == "actor":
            decision, matched_actor = await match_actor_name(db, value)
            if decision == "auto_link" and matched_actor is not None:
                # Write direct actor-event link - skip ai_suggestion staging
                from app.models.actors import ActorEventLink  # noqa: PLC0415
                db.add(ActorEventLink(
                    actor_id=matched_actor.id,
                    event_id=event_id,
                    linked_by="auto",
                ))
                await db.flush()
                continue  # do not stage as ai_suggestion
            elif decision == "discard":
                logger.info(
                    "ai_suggestion_validation_failed",
                    extra={
                        "reason": "actor_fuzzy_discard",
                        "type": stype,
                        "value": value,
                        "project_id": str(project_id),
                    },
                )
                continue  # silently drop
            # decision == "stage" falls through to normal AISuggestion creation below

        # ── CVE / ATT&CK branch: regex + catalog bool validator ───────────────
        else:
            validator = VALIDATORS.get(stype)
            if validator is None:
                logger.info(
                    "ai_suggestion_validation_failed",
                    extra={
                        "reason": "unknown_type",
                        "type": stype,
                        "value": value,
                        "project_id": str(project_id),
                    },
                )
                continue

            valid = await validator(db, value)
            if not valid:
                logger.info(
                    "ai_suggestion_validation_failed",
                    extra={
                        "reason": "regex_or_catalog_miss",
                        "type": stype,
                        "value": value,
                        "project_id": str(project_id),
                    },
                )
                continue

        row = AISuggestion(
            ai_summary_id=ai_summary_id,
            project_id=project_id,
            event_id=event_id,
            suggestion_type=stype,
            value=value,
            status="pending",
        )
        db.add(row)
        staged.append(row)

    await db.flush()
    return staged
