"""Unit tests for TIBER Markdown/HTML exporter — Jinja2 + mistune security.

Wave 0 stubs — skip-marked pending Wave 3 service layer (18-03-PLAN).
Each test documents the exact security invariants for app.services.tiber.exporters.md.

Requirements covered:
  TIBER-03 — secure HTML rendering pipeline; autoescape=True; | safe BANNED

Security invariants enforced by these tests (and by .semgrep.yml rules):
  1. Jinja2 Environment autoescape resolves True for .html templates
  2. mistune HTMLRenderer(escape=True) escapes raw HTML in analyst input
  3. jinja2.Markup() wrapping pattern avoids need for | safe filter
  4. Template lives at backend/app/templates/tiber/report.md.j2

NOTE: No `import weasyprint` at module level — subprocess isolation requires
the long-lived worker process never import WeasyPrint directly.
"""
from __future__ import annotations

import pytest

# No pytestmark — unit tests are the default (not integration-marked)


# ---------------------------------------------------------------------------
# TIBER-03: Jinja2 autoescape enabled for HTML templates
# ---------------------------------------------------------------------------


def test_jinja2_autoescape_enabled() -> None:
    """Jinja2 Environment.autoescape resolves True for .html extension.

    The md exporter must configure autoescape=select_autoescape(['html', 'xml'])
    so that any variable interpolated into an HTML template is escaped by default.
    autoescape=False is an SSTI/XSS risk — banned via Semgrep autoescape-off rule.

    Test strategy:
      1. Import _jinja_env from app.services.tiber.exporters.md
      2. Call env.is_undefined("") to confirm env exists
      3. Assert env.autoescape('report.html') is True
    """
    from app.services.tiber.exporters.md import _jinja_env

    # Jinja2 autoescape is a callable or bool; check it resolves True for .html
    autoescape_for_html = _jinja_env.autoescape
    if callable(autoescape_for_html):
        result = autoescape_for_html("report.html")
    else:
        result = bool(autoescape_for_html)

    assert result is True, (
        f"Jinja2 autoescape is {autoescape_for_html!r} — must be True for .html. "
        "XSS risk: analyst-authored content would reach raw HTML without escaping."
    )


# ---------------------------------------------------------------------------
# TIBER-03: mistune escape=True blocks raw HTML injection
# ---------------------------------------------------------------------------


def test_mistune_escape_true_default() -> None:
    """<script>alert(1)</script> in analyst markdown renders as escaped text.

    mistune.HTMLRenderer(escape=True) converts raw HTML tags to their entity
    equivalents (&lt;script&gt;...) so they appear as visible text in the output
    rather than as executable HTML elements.

    Test strategy:
      1. Import render_section_markdown from app.services.tiber.exporters.md
      2. Call it with a string containing a raw <script> tag
      3. Assert the output does NOT contain '<script>' (literal open tag)
      4. Assert the output DOES contain '&lt;script&gt;' or 'alert(1)' (escaped text)
    """
    from app.services.tiber.exporters.md import render_section_markdown

    xss_payload = "<script>alert(1)</script>"
    output = render_section_markdown(xss_payload)

    assert "<script>" not in output, (
        f"XSS RISK: mistune escape=True failed — raw <script> tag in output: {output!r}. "
        "HTMLRenderer(escape=True) must be used, not escape=False or create_markdown()."
    )
    # escaped form should appear in output (as visible text, not executable)
    assert ("&lt;" in output or "alert(1)" in output), (
        f"Expected escaped form of payload in output, got: {output!r}"
    )


# ---------------------------------------------------------------------------
# TIBER-03: Markup() wrapping avoids | safe filter
# ---------------------------------------------------------------------------


def test_markup_wrapping_avoids_safe_filter() -> None:
    """Pre-rendered HTML wrapped in jinja2.Markup() renders without | safe filter.

    When a section's analyst markdown is pre-rendered by mistune to HTML, the
    resulting HTML string must reach the Jinja2 template without double-escaping.
    The correct pattern: wrap in jinja2.Markup(rendered_html) and pass as context.
    The template uses {{ section_content }} (no | safe) — autoescape respects Markup.

    Test strategy:
      1. Create a minimal Jinja2 Environment with autoescape=True
      2. Render a template string that outputs {{ section_content }}
      3. Pass section_content = Markup('<p>Hello</p>')
      4. Assert the output contains <p>Hello</p> (NOT &lt;p&gt;)
      5. Pass section_content = '<p>Hello</p>' (plain string, no Markup)
      6. Assert the output contains &lt;p&gt; (escaped — double encoding prevented)
    """
    from jinja2 import Environment, select_autoescape
    from markupsafe import Markup

    env = Environment(autoescape=select_autoescape(["html"]))
    template = env.from_string("{{ section_content }}")

    # Markup-wrapped pre-rendered HTML passes through without double-escaping
    wrapped = Markup("<p>Hello <b>World</b></p>")
    output_wrapped = template.render(section_content=wrapped)
    assert "<p>Hello" in output_wrapped, (
        f"Markup-wrapped HTML was double-escaped: {output_wrapped!r}"
    )
    assert "&lt;p&gt;" not in output_wrapped, (
        f"Markup-wrapped HTML was unexpectedly escaped: {output_wrapped!r}"
    )

    # Plain string (NOT Markup) must be escaped by autoescape
    plain = "<p>Hello <b>World</b></p>"
    output_plain = template.render(section_content=plain)
    assert "&lt;p&gt;" in output_plain, (
        f"Plain string was NOT escaped by autoescape=True: {output_plain!r}"
    )
    assert "<p>Hello" not in output_plain, (
        f"Plain string rendered as raw HTML — autoescape is broken: {output_plain!r}"
    )


# ---------------------------------------------------------------------------
# TIBER-03: Template filename location
# ---------------------------------------------------------------------------


def test_template_filename_template() -> None:
    """Section template lives at backend/app/templates/tiber/report.md.j2.

    The Jinja2 FileSystemLoader must be configured to load from app/templates/tiber/
    and the main markdown report template must exist at report.md.j2.

    Test strategy:
      1. Import _jinja_env from app.services.tiber.exporters.md
      2. Assert env.loader is a FileSystemLoader (not BaseLoader or DictLoader)
      3. Call env.get_template("report.md.j2") — must not raise TemplateNotFound
      4. Verify the template has at least one {{ variable }} or {% block %}
    """
    import pathlib
    from jinja2 import FileSystemLoader

    from app.services.tiber.exporters.md import _jinja_env

    assert isinstance(_jinja_env.loader, FileSystemLoader), (
        f"Expected FileSystemLoader, got {type(_jinja_env.loader).__name__}. "
        "Template must be file-based (not DictLoader) to prevent SSTI."
    )

    # Template file must exist
    template = _jinja_env.get_template("report.md.j2")
    assert template is not None, "report.md.j2 template not found via FileSystemLoader"

    # Template source must contain at least one Jinja2 construct
    source, _, _ = _jinja_env.loader.get_source(_jinja_env, "report.md.j2")
    assert "{{" in source or "{%" in source, (
        f"report.md.j2 template appears to have no Jinja2 constructs: {source[:100]!r}"
    )
