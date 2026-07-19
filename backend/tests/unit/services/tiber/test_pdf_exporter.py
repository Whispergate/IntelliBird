"""Unit tests for TIBER PDF exporter - WeasyPrint subprocess isolation.

Wave 0 stubs - skip-marked pending Wave 3 service layer (18-03-PLAN).
Each test documents the subprocess isolation contract for
app.services.tiber.exporters.pdf.

Requirements covered:
  TIBER-03 - WeasyPrint subprocess isolation; PDF truncation at 500 events

Key invariants tested:
  1. subprocess.run called with ["weasyprint", input_path, output_path]
     with timeout=120 and check=True
  2. NO `import weasyprint` at module level in app/workers/reports.py
     (subprocess isolation: WeasyPrint must not be imported in the long-lived process)
  3. top_events list is truncated at 500 rows when input exceeds cap

NOTE: This module itself must NOT import weasyprint (validates isolation).
"""
from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch


# No pytestmark - unit tests are the default (not integration-marked)

# Defensive: confirm weasyprint is NOT imported at test module level
# (if we imported it here, we'd be violating the same rule we test)
assert "weasyprint" not in dir(), "weasyprint must not be imported at module level"


# ---------------------------------------------------------------------------
# TIBER-03: subprocess isolation - weasyprint CLI via subprocess.run
# ---------------------------------------------------------------------------


def test_subprocess_isolation() -> None:
    """generate_pdf_bytes calls subprocess.run(["weasyprint", ...], timeout=120, check=True).

    WeasyPrint must NEVER be imported in the long-lived Dramatiq worker process.
    The exporter invokes the `weasyprint` CLI via subprocess.run so that:
      - WeasyPrint's C library (pango/cairo/fontconfig) RSS is reclaimed on process exit
      - SIGKILL fires after timeout= seconds if rendering stalls
      - CalledProcessError on non-zero exit propagates to Dramatiq actor for retry

    Test strategy:
      1. Patch subprocess.run with a MagicMock that writes a fake PDF output file
      2. Call generate_pdf_bytes("<html>...</html>")
      3. Assert subprocess.run was called once
      4. Assert call_args[0][0] starts with ["weasyprint", ...]
      5. Assert timeout=120 was passed as keyword arg
      6. Assert check=True was passed as keyword arg
      7. Assert NO `import weasyprint` statement exists in app/workers/reports.py
         (grep assertion - the module may not exist yet in Wave 0)
    """
    from app.services.tiber.exporters.pdf import generate_pdf_bytes

    fake_pdf_bytes = b"%PDF-1.4 fake pdf content"

    def mock_subprocess_run(cmd, *args, **kwargs):
        # Simulate WeasyPrint writing output file
        output_path = pathlib.Path(cmd[-1])  # last arg is output path
        output_path.write_bytes(fake_pdf_bytes)
        mock_result = MagicMock()
        mock_result.returncode = 0
        return mock_result

    with patch("subprocess.run", side_effect=mock_subprocess_run) as mock_run:
        result = generate_pdf_bytes("<html><body><p>TIBER Report</p></body></html>")

    assert result == fake_pdf_bytes, (
        f"generate_pdf_bytes did not return the bytes written by the subprocess mock. "
        f"Got {result[:50]!r}"
    )

    mock_run.assert_called_once()
    call_args = mock_run.call_args

    # cmd must be a list starting with "weasyprint"
    cmd = call_args[0][0]
    assert isinstance(cmd, list), f"subprocess.run must be called with a list, got {type(cmd)}"
    assert cmd[0] == "weasyprint", (
        f"subprocess.run first arg must be 'weasyprint', got {cmd[0]!r}"
    )

    # timeout and check must be set
    kwargs = call_args[1]
    assert kwargs.get("timeout") == 120, (
        f"timeout must be 120 seconds, got {kwargs.get('timeout')!r}. "
        "See RESEARCH.md Pattern 1 + Pitfall 6."
    )
    assert kwargs.get("check") is True, (
        f"check=True must be set to raise CalledProcessError on WeasyPrint failure. "
        f"Got check={kwargs.get('check')!r}"
    )

    # Confirm NO `import weasyprint` in reports.py worker module
    reports_worker = pathlib.Path("app/workers/reports.py")
    if reports_worker.exists():
        source = reports_worker.read_text()
        assert "import weasyprint" not in source, (
            "SUBPROCESS ISOLATION VIOLATED: `import weasyprint` found in reports.py. "
            "WeasyPrint must NOT be imported in the long-lived Dramatiq worker process. "
            "See RESEARCH.md Pitfall 1 + Pattern 1."
        )


# ---------------------------------------------------------------------------
# TIBER-03: top_events list truncated at 500 rows
# ---------------------------------------------------------------------------


def test_pdf_truncates_event_list_at_500() -> None:
    """top_events list passed to PDF template is trimmed at 500 rows.

    A Threat Landscape section with 500+ events causes WeasyPrint to time out
    (Pitfall 6) and can produce a PDF exceeding the 50MB BYTEA cap.
    The PDF exporter must truncate the event list at 500 before rendering.

    Test strategy:
      1. Create a report_data dict with tl_top_events containing 600 mock events
      2. Call prepare_report_data_for_pdf(report_data) (or the truncation step)
      3. Assert len(result["tl_top_events"]) == 500
      4. With exactly 500 events → assert len(result["tl_top_events"]) == 500 (no change)
      5. With 20 events (default) → assert len(result["tl_top_events"]) == 20 (no change)
    """
    from app.services.tiber.exporters.pdf import prepare_report_data_for_pdf

    # 600 events - must be truncated to 500
    report_data_600 = {
        "tl_top_events": [{"id": f"evt-{i}", "title": f"Event {i}"} for i in range(600)],
        "title": "Test Report",
    }
    result_600 = prepare_report_data_for_pdf(report_data_600)
    assert len(result_600["tl_top_events"]) == 500, (
        f"Expected 500 events after truncation, got {len(result_600['tl_top_events'])}. "
        "See RESEARCH.md Pitfall 6: 500+ events cause WeasyPrint timeout."
    )

    # Exactly 500 - no change
    report_data_500 = {
        "tl_top_events": [{"id": f"evt-{i}", "title": f"Event {i}"} for i in range(500)],
        "title": "Test Report",
    }
    result_500 = prepare_report_data_for_pdf(report_data_500)
    assert len(result_500["tl_top_events"]) == 500

    # 20 events (default) - no change
    report_data_20 = {
        "tl_top_events": [{"id": f"evt-{i}", "title": f"Event {i}"} for i in range(20)],
        "title": "Test Report",
    }
    result_20 = prepare_report_data_for_pdf(report_data_20)
    assert len(result_20["tl_top_events"]) == 20
