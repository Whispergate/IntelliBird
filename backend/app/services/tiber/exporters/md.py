"""TIBER Markdown/HTML exporter - TIBER-03.

Security invariants (enforced here + via Semgrep .semgrep.yml rules):
  1. Jinja2 Environment autoescape=select_autoescape(['html', 'xml']) - MANDATORY
  2. mistune HTMLRenderer(escape=True) - MANDATORY; prevents XSS via analyst input
  3. Pre-rendered markdown HTML wrapped in markupsafe.Markup() before template context
     → template uses {{ var }} (autoescaped); pipe-safe filter is BANNED per Semgrep
  4. File-based template only - no inline template strings (SSTI prevention)
  5. Template path: backend/app/templates/tiber/report.md.j2

H-5: Event list truncated at EVENT_TRUNCATE_CAP (500) before template rendering.

References:
  RESEARCH.md Pattern 2 (mistune + Jinja2 secure rendering)
  CONTEXT.md §Auto-populate §Section completeness gate
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import mistune
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from app.services.tiber.cbest import relabel_cif_to_cbs

# ---------------------------------------------------------------------------
# mistune: escape=True is explicit (default in 3.x but explicit for audit trail)
# NEVER use escape=False - that passes raw HTML from analyst input to template.
# ---------------------------------------------------------------------------
_md_renderer = mistune.HTMLRenderer(escape=True)
_markdown = mistune.Markdown(renderer=_md_renderer)

# ---------------------------------------------------------------------------
# Jinja2 Environment - file-based loader, autoescape=True for HTML/XML.
# FileSystemLoader path: resolve from this file's location up to app/templates/tiber/
# Depth: exporters/md.py → exporters/ → tiber/ → services/ → app/ + templates/tiber/
# parents[0] = exporters/
# parents[1] = tiber/
# parents[2] = services/
# parents[3] = app/
# ---------------------------------------------------------------------------
_TEMPLATE_DIR = Path(__file__).resolve().parents[3] / "templates" / "tiber"

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    keep_trailing_newline=True,
)

# H-5: Truncation cap for Threat Landscape event list in PDF/MD output.
# Prevents WeasyPrint timeout + 50MB BYTEA cap violation on large reports.
EVENT_TRUNCATE_CAP: int = 500


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_section_markdown(md_text: str) -> str:
    """Render analyst-authored Markdown to HTML.

    escape=True ensures raw HTML tags in analyst input (e.g. <script>alert(1)</script>)
    are escaped to &lt;script&gt; rather than rendered as live HTML elements.

    Args:
        md_text: Analyst-authored Markdown string.

    Returns:
        HTML string with special characters escaped (XSS-safe).
    """
    return _markdown(md_text or "")  # type: ignore[return-value]


def render_markdown_export(
    report: Any,
    actors: list[Any] | None = None,
    scenarios: list[Any] | None = None,
) -> bytes:
    """Render full 6-section TIBER report as Markdown bytes.

    Applies CBEST relabelling to all narrative text fields when report.cbest_mode=True.
    Truncates report.tl_top_events at EVENT_TRUNCATE_CAP (500 rows) - H-5.
    Pre-renders markdown narrative fields via mistune (escape=True) and wraps in
    Markup() so the Jinja2 template can output them without | safe.

    Args:
        report: TiberReport ORM object or duck-typed equivalent.
        actors: List of TiberActorProfile ORM objects (or duck-typed).
        scenarios: List of TiberScenario ORM objects (or duck-typed).

    Returns:
        UTF-8 encoded Markdown/HTML bytes.
    """
    if actors is None:
        actors = getattr(report, "actors", []) or []
    if scenarios is None:
        scenarios = getattr(report, "scenarios", []) or []

    cbest = getattr(report, "cbest_mode", False)

    def _relabel(text: str | None) -> str:
        return relabel_cif_to_cbs(text or "", cbest)

    # Truncate event list (H-5)
    tl_events = list(getattr(report, "tl_top_events", []) or [])
    if len(tl_events) > EVENT_TRUNCATE_CAP:
        tl_events = tl_events[:EVENT_TRUNCATE_CAP]

    # Pre-render markdown fields via mistune + wrap in Markup (no | safe needed)
    tl_narrative_html = Markup(render_section_markdown(_relabel(getattr(report, "tl_analyst_narrative", None))))
    aia_summary_html = Markup(render_section_markdown(_relabel(getattr(report, "aia_summary_text", None))))
    scenario_x_html = Markup(render_section_markdown(_relabel(getattr(report, "scenario_x_narrative", None))))

    # Filter to selected scenarios only
    selected_scenarios = [s for s in scenarios if getattr(s, "selected_for_inclusion", False)]

    # Build per-actor context (relabelled)
    actor_contexts = []
    for actor in actors:
        actor_contexts.append({
            "name": _relabel(getattr(actor, "name", "")),
            "motivation": _relabel(getattr(actor, "motivation", "") or ""),
            "capability_assessment": _relabel(getattr(actor, "capability_assessment", "") or ""),
            "relevance_to_target": _relabel(getattr(actor, "relevance_to_target", "") or ""),
        })

    # Build per-scenario context (relabelled)
    scenario_contexts = []
    for scenario in selected_scenarios:
        ai_narrative_html = Markup(
            render_section_markdown(_relabel(getattr(scenario, "ai_draft_narrative", None)))
        )
        scenario_contexts.append({
            "actor_id": str(getattr(scenario, "actor_id", "") or ""),
            "cif_or_cbs_label": _relabel(getattr(scenario, "cif_or_cbs_label", "") or ""),
            "objective_type": str(getattr(scenario, "objective_type", "") or ""),
            "attack_technique_id": getattr(scenario, "attack_technique_id", "") or "",
            "procedure_text": _relabel(getattr(scenario, "procedure_text", "") or ""),
            "ai_draft_narrative_html": ai_narrative_html,
        })

    template = _jinja_env.get_template("report.md.j2")
    rendered = template.render(
        report_title=getattr(report, "title", "TIBER Report"),
        engagement_window_start=getattr(report, "engagement_window_start", None),
        engagement_window_end=getattr(report, "engagement_window_end", None),
        in_scope_assets=getattr(report, "in_scope_assets", []) or [],
        out_of_scope_assets=getattr(report, "out_of_scope_assets", []) or [],
        aia_summary_html=aia_summary_html,
        aia_recommendations=getattr(report, "aia_recommendations", []) or [],
        tl_narrative_html=tl_narrative_html,
        tl_top_events=tl_events,
        actors=actor_contexts,
        selected_scenarios=scenario_contexts,
        scenario_x_html=scenario_x_html,
        cbest_mode=cbest,
    )
    return rendered.encode("utf-8")
