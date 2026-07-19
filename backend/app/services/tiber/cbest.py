"""CBEST mode relabel helper - TIBER-01.

Replaces TIBER-EU "Critical Infrastructure Function" (CIF) terminology with
CBEST "Critical Business Service" (CBS) in report output when cbest_mode=True.

The relabel is surface-only - same DB columns store both. Only output rendering
(exporters + UI labels) is affected when cbest_mode is True on the TiberReport row.

Patterns applied (case-sensitive, whole-word boundaries via \\b regex):
  "Critical Infrastructure Function"  →  "Critical Business Service"
  "CIF"                               →  "Critical Business Service"

Reference: Bank of England CBEST Implementation Guide; CONTEXT.md §CBEST mode toggle.
"""
from __future__ import annotations

import re

# Ordered: longer pattern first to avoid partial replacements
_CIF_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bCritical Infrastructure Function\b"), "Critical Business Service"),
    (re.compile(r"\bCIF\b"), "Critical Business Service"),
]


def relabel_cif_to_cbs(text: str, cbest_mode: bool) -> str:
    """Replace CIF terminology with CBS when cbest_mode is True.

    Args:
        text: Input text string (analyst narrative, scenario field, etc.)
        cbest_mode: When True, apply the CIF → Critical Business Service relabels.
                    When False, return text unchanged.

    Returns:
        Relabelled string if cbest_mode is True; original text otherwise.
    """
    if not cbest_mode or not text:
        return text
    out = text
    for pattern, replacement in _CIF_PATTERNS:
        out = pattern.sub(replacement, out)
    return out
