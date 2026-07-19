"""TIBER PDF exporter - TIBER-03.

WeasyPrint subprocess isolation (H-5 RSS mitigation):
  NEVER import weasyprint at module level.
  NEVER use in-process WeasyPrint API (HTML(string=...).write_pdf()).
  ALWAYS use subprocess.run(["weasyprint", input_path, output_path]).

Why subprocess? WeasyPrint uses Pango/Cairo/fontconfig C libraries whose caches
are NOT freed after in-process use. After 5-10 PDFs the worker container OOMs
(GitHub issues #611, #671, #1496). The subprocess exits after each PDF, reclaiming
all C library memory. SIGKILL fires on timeout= expiry.

H-5 truncation: tl_top_events list capped at EVENT_TRUNCATE_CAP (500) by
prepare_report_data_for_pdf() before any rendering. This prevents WeasyPrint
timeout and 50MB BYTEA cap violation.

References:
  RESEARCH.md Pattern 1 (WeasyPrint subprocess)
  RESEARCH.md Pitfall 1 (RSS accumulation), Pitfall 6 (PDF timeout + truncation)
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PDF_TIMEOUT_SECONDS: int = 120

# H-5: Hard truncation cap for Threat Landscape event list in PDF template.
EVENT_TRUNCATE_CAP: int = 500


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def prepare_report_data_for_pdf(report_data: dict[str, Any]) -> dict[str, Any]:
    """Apply PDF-specific pre-processing to report data before template rendering.

    Currently performs:
    - H-5 truncation: tl_top_events capped at EVENT_TRUNCATE_CAP (500 rows)

    Args:
        report_data: Dict of template context data (from render_markdown_export context
                     or equivalent). Modified copy is returned; original not mutated.

    Returns:
        New dict with tl_top_events truncated to at most EVENT_TRUNCATE_CAP rows.
    """
    result = dict(report_data)
    events = result.get("tl_top_events")
    if isinstance(events, list) and len(events) > EVENT_TRUNCATE_CAP:
        result["tl_top_events"] = events[:EVENT_TRUNCATE_CAP]
    return result


def generate_pdf_bytes(html_content: str, timeout: int = PDF_TIMEOUT_SECONDS) -> bytes:
    """Generate PDF bytes from HTML via WeasyPrint subprocess.

    Subprocess isolation guarantees:
    - RSS is reclaimed when subprocess exits (WeasyPrint memory growth is isolated)
    - SIGKILL on timeout (subprocess.run timeout= triggers SIGKILL after timeout)
    - No WeasyPrint import in the long-lived worker process
    - Non-zero exit code raises CalledProcessError → Dramatiq actor retry

    The HTML content should already have the event list truncated via
    prepare_report_data_for_pdf() before rendering. This function does NOT
    re-check the truncation - it trusts the caller.

    Args:
        html_content: Rendered HTML string (Jinja2 output, already autoescaped).
        timeout: Subprocess timeout in seconds. Default 120s for A4 TIBER PDF.

    Returns:
        PDF bytes from WeasyPrint.

    Raises:
        subprocess.TimeoutExpired: if WeasyPrint rendering exceeds timeout.
        subprocess.CalledProcessError: if weasyprint exits non-zero.
        FileNotFoundError: if weasyprint CLI is not installed in PATH.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        html_path = Path(tmpdir) / "input.html"
        pdf_path = Path(tmpdir) / "output.pdf"
        html_path.write_text(html_content, encoding="utf-8")

        subprocess.run(
            ["weasyprint", str(html_path), str(pdf_path)],
            timeout=timeout,
            capture_output=True,
            check=True,
        )

        return pdf_path.read_bytes()
