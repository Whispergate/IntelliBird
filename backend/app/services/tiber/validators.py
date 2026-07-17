"""TIBER report completeness validators — TIBER-01/02.

Two validation functions:
  completeness_check(report) -> dict[str, list[str]]
    Maps section key → list of missing required field names.
    Empty dict means all sections are complete (export allowed).
    Section keys: "scope", "aia", "threat_landscape", "actor_profiles", "scenarios", "scenario_x"

  scenario_gate_check(scenarios) -> list[str]
    Returns a list of error strings. Empty list means gate passes.
    Validates:
      - 3 ≤ selected_count ≤ (len(scenarios) must be ≤ 6)
      - Each selected scenario has all 5 required fields non-null

Requirements: TIBER-01 completeness gate, TIBER-02 scenario stepper gate.
CONTEXT.md §Section completeness gate, §Scenario count gate.
"""
from __future__ import annotations

from typing import Any


def completeness_check(report: Any) -> dict[str, list[str]]:
    """Check all 6 TIBER report sections for required fields.

    Args:
        report: A TiberReport ORM object or duck-typed equivalent with the
                standard field attributes. The report object's .actors and
                .scenarios attributes are used for the actor/scenario sections.

    Returns:
        dict mapping section key → list of missing required field names.
        Empty dict means fully complete (export gate passes).

    Section keys and required fields per CONTEXT.md §Section completeness gate:
      "scope":
          engagement_window_start, engagement_window_end (both non-null)
          in_scope_assets (list with >= 1 entry)
          out_of_scope_assets (must be set; can be empty list, but not None)
      "aia":
          aia_summary_text (non-empty)
          aia_recommendations (list with >= 1 entry)
      "threat_landscape":
          tl_top_events (list with >= 5 entries)
          tl_analyst_narrative (non-empty)
      "actor_profiles":
          actors list >= 3 entries
          each actor: name, motivation, capability_assessment, relevance_to_target
      "scenarios":
          >= 3 scenarios with selected_for_inclusion=True
      "scenario_x":
          scenario_x_narrative (non-empty)
    """
    missing: dict[str, list[str]] = {}

    # --- 1. Scope of Intelligence Research ---
    scope_missing: list[str] = []
    if not getattr(report, "engagement_window_start", None):
        scope_missing.append("engagement_window")
    if not getattr(report, "engagement_window_end", None):
        scope_missing.append("engagement_window")
    # Deduplicate engagement_window if both start and end are missing
    scope_missing_deduped: list[str] = []
    _seen = set()
    for item in scope_missing:
        if item not in _seen:
            scope_missing_deduped.append(item)
            _seen.add(item)
    scope_missing = scope_missing_deduped

    in_scope = getattr(report, "in_scope_assets", None)
    if not in_scope or len(in_scope) < 1:
        scope_missing.append("in_scope_assets")

    out_of_scope = getattr(report, "out_of_scope_assets", None)
    if out_of_scope is None:
        scope_missing.append("out_of_scope_assets")
    # Note: empty list [] is valid — only None fails

    if scope_missing:
        missing["scope"] = scope_missing

    # --- 2. Actionable Intelligence Assessment ---
    aia_missing: list[str] = []
    if not getattr(report, "aia_summary_text", None):
        aia_missing.append("summary_text")
    aia_recs = getattr(report, "aia_recommendations", None)
    if not aia_recs or len(aia_recs) < 1:
        aia_missing.append("analyst_recommendations")
    if aia_missing:
        missing["aia"] = aia_missing

    # --- 3. Threat Landscape ---
    tl_missing: list[str] = []
    tl_events = getattr(report, "tl_top_events", None)
    if not tl_events or len(tl_events) < 5:
        tl_missing.append("top_events")
    if not getattr(report, "tl_analyst_narrative", None):
        tl_missing.append("analyst_narrative")
    if tl_missing:
        missing["threat_landscape"] = tl_missing

    # --- 4. Threat Actor Profiles ---
    actor_missing: list[str] = []
    actors = getattr(report, "actors", []) or []
    if len(actors) < 3:
        actor_missing.append("actors")
    for i, actor in enumerate(actors):
        for field_name in ("name", "motivation", "capability_assessment", "relevance_to_target"):
            if not getattr(actor, field_name, None):
                actor_missing.append(f"actors[{i}].{field_name}")
    if actor_missing:
        missing["actor_profiles"] = actor_missing

    # --- 5. Threat Scenarios ---
    scenarios = getattr(report, "scenarios", []) or []
    selected = [s for s in scenarios if getattr(s, "selected_for_inclusion", False)]
    if len(selected) < 3:
        missing["scenarios"] = ["selected_count"]

    # --- 6. Scenario X ---
    if not getattr(report, "scenario_x_narrative", None):
        missing["scenario_x"] = ["narrative_text"]

    return missing


def scenario_gate_check(scenarios: list[Any]) -> list[str]:
    """Validate scenario longlist count gate and per-scenario required fields.

    Args:
        scenarios: List of TiberScenario ORM objects or duck-typed equivalents.
                   Each must have: id, actor_id, cif_or_cbs_label, objective_type,
                   attack_technique_id, procedure_text, selected_for_inclusion.

    Returns:
        List of error strings. Empty list means gate passes (export allowed).
        Errors include:
          - count errors (too few selected, too many in longlist)
          - per-scenario field errors for selected scenarios

    Gate rules per CONTEXT.md §Scenario count gate:
      - Total longlist count must be <= 6 (max)
      - At least 3 scenarios must be selected_for_inclusion=True
      - Each selected scenario must have all 5 required fields non-null:
          actor_id, cif_or_cbs_label, objective_type, attack_technique_id, procedure_text
    """
    errors: list[str] = []

    # Max longlist size check
    if len(scenarios) > 6:
        errors.append(
            f"longlist_exceeds_max: {len(scenarios)} scenarios in longlist, max is 6"
        )

    # Selected count check
    selected = [s for s in scenarios if getattr(s, "selected_for_inclusion", False)]
    if len(selected) < 3:
        errors.append(
            f"selected_count: {len(selected)} selected, min is 3"
        )

    # Per-scenario required field checks (only for selected scenarios)
    _VALID_OBJECTIVES = {"availability", "integrity", "confidentiality"}
    for scenario in selected:
        scenario_id = getattr(scenario, "id", "<unknown>")
        if not getattr(scenario, "actor_id", None):
            errors.append(f"scenario {scenario_id}: actor_id is required")
        if not getattr(scenario, "cif_or_cbs_label", None):
            errors.append(f"scenario {scenario_id}: cif_or_cbs_label is required")
        objective = getattr(scenario, "objective_type", None)
        if not objective:
            errors.append(f"scenario {scenario_id}: objective_type is required")
        elif str(objective) not in _VALID_OBJECTIVES:
            errors.append(
                f"scenario {scenario_id}: objective_type={objective!r} is invalid "
                f"(must be one of {sorted(_VALID_OBJECTIVES)})"
            )
        if not getattr(scenario, "attack_technique_id", None):
            errors.append(f"scenario {scenario_id}: attack_technique_id is required")
        if not getattr(scenario, "procedure_text", None):
            errors.append(f"scenario {scenario_id}: procedure_text is required")

    return errors
