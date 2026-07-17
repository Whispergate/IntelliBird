"""Unit tests for TIBER report section completeness and validation gates.

Wave 0 stubs — skip-marked pending Wave 3 service layer (18-03-PLAN).
Each test documents the exact behaviour expected from app.services.tiber.validators.

Requirements covered:
  TIBER-01 — section completeness gate (completeness_check)
  TIBER-02 — scenario stepper 5-step validation gate (scenario_gate_check)
  TIBER-03 — history list query excludes content_bytea column
  AI-08    — ai_draft_scenario_narrative actor must be on queue_name="ai"
"""
from __future__ import annotations

import pytest

# No pytestmark — unit tests are the default (not integration-marked)


# ---------------------------------------------------------------------------
# TIBER-01: Section completeness gate
# ---------------------------------------------------------------------------


def test_section_completeness_gate_required_fields() -> None:
    """completeness_check(report) returns dict[section, list[missing_field]].

    Required-field semantics per CONTEXT.md locked decisions:
      - Scope of Intelligence Research:
          engagement_window (start+end non-null), in_scope_assets[]>=1,
          out_of_scope_assets (must be set, can be empty array)
      - Actionable Intelligence Assessment:
          summary_text (non-empty), analyst_recommendations[]>=1
      - Threat Landscape:
          top_events[]>=5 (auto-populated), analyst_narrative (non-empty text)
      - Threat Actor Profiles:
          actors[]>=3 each with name, motivation, capability_assessment,
          relevance_to_target
      - Threat Scenarios:
          >=3 selected scenarios from longlist of <=6
      - Scenario X:
          narrative_text non-empty

    Test strategy:
      1. Build a minimal-valid report object (all required fields set)
         → completeness_check returns {} (empty dict = fully complete)
      2. Strip engagement_window_start → section 'scope' has ['engagement_window']
      3. Set in_scope_assets=[] → section 'scope' has ['in_scope_assets']
      4. Set out_of_scope_assets=None → section 'scope' has ['out_of_scope_assets']
      5. Set actors=[] → section 'actor_profiles' has ['actors']
      6. Set selected scenario count to 2 → section 'scenarios' has ['selected_count']
    """
    from app.services.tiber.validators import completeness_check

    # 1. Fully valid report — empty dict returned
    valid_report = _make_valid_report()
    result = completeness_check(valid_report)
    assert result == {}, f"Expected fully-complete report to pass, got: {result}"

    # 2. Missing engagement window start
    report_no_window = _make_valid_report()
    report_no_window.engagement_window_start = None
    result2 = completeness_check(report_no_window)
    assert "scope" in result2
    assert "engagement_window" in result2["scope"]

    # 3. Empty in_scope_assets
    report_empty_assets = _make_valid_report()
    report_empty_assets.in_scope_assets = []
    result3 = completeness_check(report_empty_assets)
    assert "scope" in result3
    assert "in_scope_assets" in result3["scope"]

    # 4. out_of_scope_assets not set (None — must be at least empty array)
    report_null_oos = _make_valid_report()
    report_null_oos.out_of_scope_assets = None
    result4 = completeness_check(report_null_oos)
    assert "scope" in result4
    assert "out_of_scope_assets" in result4["scope"]

    # 5. Too few actors
    report_few_actors = _make_valid_report()
    report_few_actors.actors = report_few_actors.actors[:2]  # only 2, need >=3
    result5 = completeness_check(report_few_actors)
    assert "actor_profiles" in result5
    assert "actors" in result5["actor_profiles"]

    # 6. Too few selected scenarios
    report_few_scenarios = _make_valid_report()
    for s in report_few_scenarios.scenarios:
        s.selected_for_inclusion = False
    report_few_scenarios.scenarios[0].selected_for_inclusion = True
    report_few_scenarios.scenarios[1].selected_for_inclusion = True
    result6 = completeness_check(report_few_scenarios)
    assert "scenarios" in result6
    assert "selected_count" in result6["scenarios"]


# ---------------------------------------------------------------------------
# TIBER-02: Scenario stepper 5-step gate
# ---------------------------------------------------------------------------


def test_scenario_completeness() -> None:
    """scenario_gate_check(scenarios) validates each selected scenario has all required fields.

    A selected scenario must have:
      - actor_id (non-null FK to tiber_actor_profiles)
      - cif_or_cbs_label (non-empty text)
      - objective_type in {'availability', 'integrity', 'confidentiality'}
      - attack_technique_id (non-null text)
      - procedure_text (non-empty text)

    Count constraints: 3-6 scenarios in longlist; min 3 must be selected.

    Test strategy:
      1. 3 fully-valid selected scenarios → scenario_gate_check returns []
      2. Selected scenario missing actor_id → returns error for that scenario id
      3. objective_type='invalid' → returns error
      4. Only 2 selected → gate fails with count error
      5. 7 scenarios in longlist → gate fails with longlist_exceeds_max error
    """
    from app.services.tiber.validators import scenario_gate_check

    # 1. Valid: 3 selected scenarios, all fields present
    valid_scenarios = [_make_valid_scenario(i, selected=True) for i in range(3)]
    errors = scenario_gate_check(valid_scenarios)
    assert errors == [], f"Expected no errors for valid scenarios, got: {errors}"

    # 2. Missing actor_id on scenario 0
    scenarios_no_actor = [_make_valid_scenario(i, selected=True) for i in range(3)]
    scenarios_no_actor[0].actor_id = None
    errors2 = scenario_gate_check(scenarios_no_actor)
    assert any("actor_id" in str(e) for e in errors2), (
        f"Expected actor_id error, got: {errors2}"
    )

    # 3. Invalid objective_type
    scenarios_bad_obj = [_make_valid_scenario(i, selected=True) for i in range(3)]
    scenarios_bad_obj[0].objective_type = "ransomware"  # not in {availability, integrity, confidentiality}
    errors3 = scenario_gate_check(scenarios_bad_obj)
    assert any("objective_type" in str(e) for e in errors3), (
        f"Expected objective_type error, got: {errors3}"
    )

    # 4. Only 2 selected
    scenarios_few = [_make_valid_scenario(i, selected=(i < 2)) for i in range(3)]
    errors4 = scenario_gate_check(scenarios_few)
    assert any("selected_count" in str(e) or "min" in str(e).lower() for e in errors4), (
        f"Expected min-selected error, got: {errors4}"
    )

    # 5. 7 scenarios in longlist (exceeds max 6)
    scenarios_too_many = [_make_valid_scenario(i, selected=(i < 3)) for i in range(7)]
    errors5 = scenario_gate_check(scenarios_too_many)
    assert any("max" in str(e).lower() or "longlist" in str(e).lower() for e in errors5), (
        f"Expected longlist_exceeds_max error, got: {errors5}"
    )


# ---------------------------------------------------------------------------
# TIBER-03: History list query excludes content_bytea
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Wave 4 — history query module not yet shipped (18-04-PLAN)")
def test_history_query_excludes_bytea(monkeypatch) -> None:
    """History list query SQL must never reference content_bytea column.

    The history sidebar loads export metadata rows (id, format, version_number,
    filename, generated_at, generated_by_user_id, report_state_at_export).
    Fetching content_bytea in this query triggers TOAST decompression for ALL
    export versions on every sidebar load — O(n * PDF_size) per page load.

    Test strategy: call get_report_history_query() from the history module,
    capture the compiled SQL string, and assert 'content_bytea' does not appear.
    """
    from app.services.tiber import history

    # get_report_history_query returns a SQLAlchemy Select construct
    import uuid
    tiber_report_id = uuid.uuid4()
    query = history.get_report_history_query(tiber_report_id)

    # Compile to SQL string (dialect-agnostic)
    from sqlalchemy.dialects import postgresql
    sql_str = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    sql_lower = sql_str.lower()

    assert "content_bytea" not in sql_lower, (
        f"BYTEA TOAST leak: history query references content_bytea column. "
        f"SQL: {sql_str[:300]}"
    )
    # Positive assertion: metadata columns ARE present
    assert "version_number" in sql_lower or "generated_at" in sql_lower, (
        f"History query missing expected metadata columns. SQL: {sql_str[:300]}"
    )


# ---------------------------------------------------------------------------
# AI-08: ai_draft_scenario_narrative actor queue assertion
# ---------------------------------------------------------------------------


def test_narrative_actor_queue(monkeypatch) -> None:
    """ai_draft_scenario_narrative Dramatiq actor must be declared on queue_name='ai'.

    Per CONTEXT.md AI-08 decision + Pitfall 7: the narrative actor belongs on the
    existing 'ai' queue (token budget tracking is queue-co-located) NOT
    on the 'reports' queue (which is for PDF/MD/STIX generation).

    Test strategy:
      1. Import ai_draft_scenario_narrative from app.workers.ai
      2. Assert actor.queue_name == "ai"
      3. Assert actor is NOT imported from app.workers.reports (wrong queue)
    """
    from app.workers.ai import ai_draft_scenario_narrative

    assert hasattr(ai_draft_scenario_narrative, "queue_name") or hasattr(
        ai_draft_scenario_narrative, "actor_name"
    ), "ai_draft_scenario_narrative is not a Dramatiq actor (missing queue_name attribute)"

    # Dramatiq actors expose .queue_name via the actor wrapper
    actor_queue = getattr(ai_draft_scenario_narrative, "queue_name", None)
    assert actor_queue == "ai", (
        f"WRONG QUEUE: ai_draft_scenario_narrative is on queue '{actor_queue}', "
        f"expected 'ai'. Token budget tracking requires ai queue co-location. "
        f"See CONTEXT.md AI-08 + RESEARCH.md Pitfall 7."
    )

    # Confirm it is NOT in reports.py (that would be the wrong module)
    import ast
    import pathlib
    reports_worker = pathlib.Path("app/workers/reports.py")
    if reports_worker.exists():
        source = reports_worker.read_text()
        assert "ai_draft_scenario_narrative" not in source, (
            "ai_draft_scenario_narrative found in reports.py — must be in ai.py only."
        )


# ---------------------------------------------------------------------------
# Helpers — only used by stubs above (not imported at module level from app/)
# ---------------------------------------------------------------------------


def _make_valid_report():
    """Construct a minimal valid TIBER report object for completeness tests.

    This is a dataclass/Pydantic-like stub used within the skip-marked tests.
    The actual schema is defined in app/schemas/tiber.py (Wave 3).
    """
    from types import SimpleNamespace

    actors = [
        SimpleNamespace(
            name=f"Actor {i}",
            motivation="Financial gain",
            capability_assessment="High",
            relevance_to_target="Direct targeting of financial sector",
        )
        for i in range(3)
    ]
    scenarios = [
        SimpleNamespace(
            id=f"scenario-{i}",
            actor_id=f"actor-{i}",
            cif_or_cbs_label="Core Banking System",
            objective_type="availability",
            attack_technique_id="T1566",
            procedure_text="Phishing campaign targeting finance staff.",
            selected_for_inclusion=True,
        )
        for i in range(3)
    ]
    return SimpleNamespace(
        engagement_window_start="2026-01-01",
        engagement_window_end="2026-03-31",
        in_scope_assets=["Core Banking System"],
        out_of_scope_assets=[],
        aia_summary_text="Intelligence assessment complete.",
        aia_recommendations=["Recommendation 1"],
        tl_top_events=[{"id": f"evt-{i}"} for i in range(5)],
        tl_analyst_narrative="The threat landscape is elevated.",
        actors=actors,
        scenarios=scenarios,
        scenario_x_narrative="Additional narrative findings.",
    )


def _make_valid_scenario(index: int, selected: bool):
    """Construct a minimal valid scenario object for scenario gate tests."""
    from types import SimpleNamespace

    return SimpleNamespace(
        id=f"scenario-{index}",
        actor_id=f"actor-{index}",
        cif_or_cbs_label="Core Banking System",
        objective_type="availability",
        attack_technique_id="T1566",
        procedure_text="Spear-phishing with credential harvesting.",
        selected_for_inclusion=selected,
    )
