"""Brand match severity scoring - pure function. No DB, no I/O.

Severity truth table (locked in 12-CONTEXT.md + 12-RESEARCH.md):

    match_source   dnstwist_success   severity
    ------------   ----------------   --------
    fts            *                  low
    ct_log         *                  medium
    dnstwist       True               high
    dnstwist       False              low     (registered perm w/ no DNS = low signal)

All other (match_source, dnstwist_success) inputs raise ValueError so callers
catch enum drift early.
"""
from __future__ import annotations

from typing import Literal

MatchSource = Literal["fts", "ct_log", "dnstwist"]
Severity = Literal["low", "medium", "high"]


def score(match_source: MatchSource, dnstwist_success: bool = False) -> Severity:
    """Return severity for a given (match_source, dnstwist_success) pair.

    See module docstring for the full truth table.
    """
    if match_source == "fts":
        return "low"
    if match_source == "ct_log":
        return "medium"
    if match_source == "dnstwist":
        return "high" if dnstwist_success else "low"
    raise ValueError(f"Unknown match_source: {match_source!r}")
