"""TIBER report exporters package — TIBER-03.

Three export formats:
  markdown  — Jinja2 + mistune, secure HTML rendering pipeline (H-6 XSS mitigation)
  pdf       — WeasyPrint subprocess isolation (H-5 RSS mitigation)
  stix      — stix2 Report SDO bundle with parse(strict=True) CI gate (M-4)
"""
