"""
DISINFO-03 — Narrative operation prompt constant and validator are present.

These tests directly import existing modules that will be MODIFIED in
Phase 33 Plan 04 to add narrative_op support.  Tests will FAIL (NameError /
KeyError) until those modifications land — this is intentional RED state.

Targets:
  - backend/app/services/llm/prompts.py        (add SYSTEM_PROMPT_NARRATIVE_OP_V1)
  - backend/app/services/llm/suggestion_validator.py  (add "narrative_op" to VALIDATORS)
  - backend/app/schemas/ai.py                  (extend suggestion_type Literal)
"""
import os
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)


def test_narrative_op_prompt_exists():
    """SYSTEM_PROMPT_NARRATIVE_OP_V1 must be defined in app.services.llm.prompts.

    Will raise NameError until Plan 04 adds the constant.
    """
    from app.services.llm.prompts import SYSTEM_PROMPT_NARRATIVE_OP_V1  # noqa: F401 — tested by import

    assert isinstance(SYSTEM_PROMPT_NARRATIVE_OP_V1, str)
    assert len(SYSTEM_PROMPT_NARRATIVE_OP_V1) > 0


def test_narrative_op_prompt_contains_claim():
    """SYSTEM_PROMPT_NARRATIVE_OP_V1 must mention 'claim' to guide the analyst.

    The prompt instructs the LLM to extract the central claim, so 'claim'
    must appear in the prompt text.
    """
    from app.services.llm.prompts import SYSTEM_PROMPT_NARRATIVE_OP_V1

    assert "claim" in SYSTEM_PROMPT_NARRATIVE_OP_V1.lower()


def test_validate_narrative_op_always_true():
    """VALIDATORS dict in suggestion_validator must include a 'narrative_op' entry.

    Will raise KeyError until Plan 04 adds the entry to the VALIDATORS dispatch
    table in app.services.llm.suggestion_validator.
    """
    from app.services.llm.suggestion_validator import VALIDATORS

    assert "narrative_op" in VALIDATORS, (
        "VALIDATORS missing 'narrative_op' key — add it in Plan 04"
    )


def test_suggestion_type_includes_narrative_op():
    """AISuggestionRead.suggestion_type Literal must include 'narrative_op'.

    Will fail until Plan 04 extends the Literal in app.schemas.ai.AISuggestionRead.
    """
    import typing

    from app.schemas.ai import AISuggestionRead

    annotation = AISuggestionRead.model_fields["suggestion_type"].annotation
    args = typing.get_args(annotation)
    assert "narrative_op" in args, (
        f"suggestion_type Literal does not include 'narrative_op'; found: {args}"
    )
