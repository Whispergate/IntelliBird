"""Prompt constants for the LiteLLM adapter — Phase 17 / AI-04.

Prompt templates are stored as code constants (NOT in DB) to minimise C-3
prompt-injection surface.  Admin UI editing of prompts is explicitly out of
scope for M2 (see 17-CONTEXT.md §Prompt templates).

Version convention: integer suffix on constant name.  Bump the suffix to
change behaviour; the old constant is kept for audit trail (git history).
``ai_summaries.prompt_template_version`` records the string constant name used
for each summary row so historical summaries are reproducible.

Builder functions construct the ``messages`` list structurally:
  messages = [{"role": "system", ...}, {"role": "user", "content": json.dumps(...)}]

The user content is ALWAYS a JSON-serialised payload.  Never use f-strings with
raw event content (C-3 mitigation).  Code-review gate:
  rg 'f".*event\\.' app/services/llm/  → must return 0 matches.
"""
from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# System prompts (role="system" content)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_V1: str = (
    "You are a SOC threat intelligence analyst. Summarise the supplied event "
    "JSON into five labelled sections: What / Who / When / Why-it-matters / "
    "Recommended-action. Use bullet points within each section. Do not invent "
    "CVE IDs, ATT&CK technique IDs, or threat-actor names that are not present "
    "in the input."
)

SYSTEM_PROMPT_DIGEST_V1: str = (
    "You are a SOC analyst writing a daily digest. Synthesise the supplied "
    "top-N events JSON into a single prose digest with markdown headings: "
    "## Highlights, ## Actor activity, ## CVE landscape, ## Recommended focus. "
    "Within each section use short bullets. Append a final line of the form "
    "'\\u2014 Summary based on N of M events' where N=top-count and M=window-count."
)

SYSTEM_PROMPT_META_V1: str = (
    "You are merging K partial event summaries into one final summary. "
    "Output the same five labelled sections as the per-event summary: "
    "What / Who / When / Why-it-matters / Recommended-action. "
    "Use bullet points within each section. "
    "Append the line '\\u2014 Content exceeded model window; summary based on top-ranked chunks' "
    "as the final line."
)

SYSTEM_PROMPT_SUGGESTIONS_V1: str = (
    "You are a threat intelligence analyst. Read the supplied event JSON "
    "(includes title, description, and a prior AI-generated summary when "
    "available) and extract structured entities. INFER MITRE ATT&CK techniques "
    "(TTPs) even when not literally named — map described behaviour to the "
    "best-fitting technique IDs (e.g. spearphishing attachment → T1566.001, "
    "credential dumping → T1003, lateral movement via PsExec → T1021.002). "
    "Prefer specific sub-technique IDs (T1566.001) over parent IDs (T1566) "
    "when the evidence supports it. "
    "Also produce up to 8 short topical TAGS — single tokens or short hyphenated "
    "phrases capturing campaign names, malware/tool families, targeted "
    "sectors, geographic focus, attack vectors, or notable behaviours "
    "(e.g. 'apt29', 'cobalt-strike', 'healthcare', 'eastern-europe', "
    "'spearphishing', 'wiper', 'zero-day'). Tags must be lowercase, "
    "alphanumeric + hyphens only, 1-32 chars each. Skip generic words like "
    "'malware', 'attack', 'security'. "
    "Return STRICT JSON with keys cve_ids[], attack_technique_ids[], "
    "actor_names[], tags[]. CVE IDs match ^CVE-\\d{4}-\\d{4,7}$. ATT&CK "
    "technique IDs match ^T\\d{4}(\\.\\d{3})?$. Do not include any other keys, "
    "prose, or markdown fences."
)

# ---------------------------------------------------------------------------
# Version tag constants — stored in ai_summaries.prompt_template_version
# ---------------------------------------------------------------------------

EVENT_SUMMARY_PROMPT_V1: str = "event_summary_v1"
DIGEST_PROMPT_V1: str = "digest_v1"
META_SUMMARY_PROMPT_V1: str = "meta_summary_v1"
SUGGESTION_EXTRACTION_PROMPT_V1: str = "suggestion_extraction_v1"

# ---------------------------------------------------------------------------
# Message builders — structural construction only (C-3 compliance)
# ---------------------------------------------------------------------------


def build_summary_messages(event_payload: dict) -> list[dict]:
    """Build messages for a single-event summary.

    The user content is json.dumps(event_payload) — never an f-string.
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPT_V1},
        {"role": "user", "content": json.dumps(event_payload, default=str)},
    ]


def build_digest_messages(events_payload: list[dict]) -> list[dict]:
    """Build messages for a daily project digest (top-N events)."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT_DIGEST_V1},
        {"role": "user", "content": json.dumps({"events": events_payload}, default=str)},
    ]


def build_meta_messages(partial_summaries: list[str]) -> list[dict]:
    """Build messages for the meta-summary (hierarchical chunking second pass)."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT_META_V1},
        {"role": "user", "content": json.dumps({"partials": partial_summaries})},
    ]


def build_suggestion_messages(event_payload: dict) -> list[dict]:
    """Build messages for entity extraction / suggestion generation."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT_SUGGESTIONS_V1},
        {"role": "user", "content": json.dumps(event_payload, default=str)},
    ]


# ---------------------------------------------------------------------------
# TIBER scenario narrative prompt — Phase 18 / AI-08
# ---------------------------------------------------------------------------

SCENARIO_NARRATIVE_PROMPT_V1: str = "scenario_narrative_v1"

SYSTEM_PROMPT_SCENARIO_NARRATIVE_V1: str = (
    "You are a TIBER threat intelligence analyst writing a scenario narrative for a "
    "Targeted Threat Intelligence Report (TTIR) under the ECB TIBER-EU / CBEST framework. "
    "Output 2-4 paragraphs of formal prose covering: "
    "(1) actor motivation and capability relative to the named target, "
    "(2) targeting rationale — why the actor would pursue this specific CIF or CBS, "
    "(3) the procedure employed to achieve the stated objective (aligned to the ATT&CK technique "
    "where supplied). "
    "Tone: professional, intelligence-led, third-person. "
    "Do not invent IOCs, CVE IDs, actor names, or ATT&CK technique IDs that are not present "
    "in the supplied context."
)


# ---------------------------------------------------------------------------
# Narrative operation classification prompt — Phase 33 / DISINFO-03
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_NARRATIVE_OP_V1: str = (
    "You are a disinformation analyst. Read the supplied social media post JSON "
    "and classify it as a narrative operation if applicable. Extract the following "
    "fields as JSON: "
    "{\"claim\": \"<core factual assertion being made>\", "
    "\"amplifier\": \"<accounts or communities spreading it>\", "
    "\"audience\": \"<apparent target demographic or community>\", "
    "\"is_narrative_op\": true|false}. "
    "Return only valid JSON. If the post is not a narrative operation, "
    "return {\"is_narrative_op\": false}. "
    "Do not invent information not present in the post."
)


# ---------------------------------------------------------------------------
# Attack path analysis prompt — Phase 35 / ATK-01
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_ATTACK_PATH_V1: str = (
    "You are a threat analyst. Given security events, output ONLY a JSON object "
    "with keys 'nodes' and 'edges' describing the MITRE ATT&CK kill-chain. "
    "nodes: array of {id:\"step_1\", technique_id:\"T1566\", tactic:\"initial-access\", "
    "name:\"short label\", confidence:0.8, rationale:\"one sentence\"}. "
    "edges: array of {from:\"step_1\", to:\"step_2\", rationale:\"reason\"}. "
    "Max 8 nodes, max 8 edges. Use only technique IDs present in the events. "
    "Return valid JSON only. No markdown, no explanation."
)

ATTACK_PATH_PROMPT_V1: str = "attack_path_v1"


def build_attack_path_messages(events_payload: dict) -> list[dict]:
    """Build messages for MITRE kill-chain reconstruction (C-3 compliant).

    events_payload must have keys: events, truncated, project_days_window.
    Never uses f-strings with raw event content.
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPT_ATTACK_PATH_V1},
        {"role": "user", "content": json.dumps(events_payload, default=str)},
    ]


def tiber_scenario_narrative_messages(scenario, actor, report) -> list[dict]:
    """Build messages for an AI-drafted TIBER scenario narrative (AI-08).

    Structural prompt construction — NO f-string of raw user-controlled text
    into a single role's content (C-3 compliance; same rule as build_summary_messages).
    The user content is json.dumps of a structured payload.

    Args:
        scenario: TiberScenario ORM object or duck-typed equivalent.
                  Must provide: cif_or_cbs_label, objective_type,
                  attack_technique_id, procedure_text.
        actor:    TiberActorProfile ORM object, or None if actor was deleted.
                  Must provide: name, motivation, capability_assessment.
        report:   TiberReport ORM object or duck-typed equivalent.
                  Must provide: title, cbest_mode.

    Returns:
        list[dict]: Structural messages list: [system_msg, user_msg].
    """
    system_msg = {
        "role": "system",
        "content": SYSTEM_PROMPT_SCENARIO_NARRATIVE_V1,
    }
    user_payload = {
        "report_title": getattr(report, "title", None),
        "cbest_mode": getattr(report, "cbest_mode", False),
        "actor_name": getattr(actor, "name", None) if actor is not None else None,
        "actor_motivation": (
            getattr(actor, "motivation", None) if actor is not None else None
        ),
        "actor_capability": (
            getattr(actor, "capability_assessment", None) if actor is not None else None
        ),
        "cif_or_cbs_label": getattr(scenario, "cif_or_cbs_label", None),
        "objective_type": str(getattr(scenario, "objective_type", "") or ""),
        "attack_technique_id": getattr(scenario, "attack_technique_id", None),
        "procedure_text": getattr(scenario, "procedure_text", None),
    }
    user_msg = {
        "role": "user",
        "content": json.dumps(user_payload, default=str),
    }
    return [system_msg, user_msg]
