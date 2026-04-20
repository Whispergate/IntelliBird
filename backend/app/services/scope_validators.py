"""Per-scope-type value validators for PRJ-02 scope rows — Phase 10.

validate_scope_row_value() is the single entrypoint; it dispatches to per-type helpers.
Each helper raises ValueError on invalid input and returns a canonicalised string.

Error messages match UI-SPEC.md §Error states byte-for-byte (localisable later):
  - CIDR: "Enter a valid CIDR block, e.g. 10.0.0.0/24."
  - FQDN: "Enter a valid domain, e.g. example.com."
  - AS:   "AS number must be a positive integer."
  - Cert: "Enter a SHA-1 (40 hex) or SHA-256 (64 hex) certificate fingerprint."

Consumed by:
  - backend/app/routers/projects.py — POST /api/projects/{id}/scope validates
    body.value before INSERT, returning 422 with the error message as detail.
  - backend/app/services/project_scope.py (downstream) — relies on CIDR values
    being parseable by PostgreSQL `inet` type for the `<<` containment operator.
"""
from __future__ import annotations

import ipaddress
import re


# RFC 1035 — length 1..253, labels 1..63 chars, alnum/hyphen, not starting/ending
# with hyphen, at least one dot, TLD >= 2 alpha chars.
_FQDN_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?\.)+[a-z]{2,}$",
    re.IGNORECASE,
)
_HEX_40 = re.compile(r"^[0-9a-fA-F]{40}$")
_HEX_64 = re.compile(r"^[0-9a-fA-F]{64}$")


def validate_cidr(value: str) -> str:
    """CIDR block (IPv4 or IPv6). Returns canonical form, e.g. '10.0.0.0/8'.

    strict=False accepts host-bits-set input (e.g. 192.168.1.5/24) and returns
    the normalised network address (192.168.1.0/24).
    """
    try:
        net = ipaddress.ip_network(value.strip(), strict=False)
    except (ValueError, TypeError) as exc:
        raise ValueError("Enter a valid CIDR block, e.g. 10.0.0.0/24.") from exc
    return str(net)


def validate_fqdn(value: str) -> str:
    """Fully-qualified domain name (RFC 1035). Returns lowercase canonical form."""
    v = value.strip().lower()
    if not _FQDN_RE.match(v):
        raise ValueError("Enter a valid domain, e.g. example.com.")
    return v


def validate_as_number(value: str) -> str:
    """ASN — 1..4294967295. Accepts 'AS12345' or '12345'. Returns canonical '12345'.

    Range: 1 to 4_294_967_295 per RFC 6793 (32-bit AS). 0 is reserved; negatives
    and non-digit inputs all raise "positive integer" — single error copy for
    the UI-SPEC.
    """
    s = value.strip().upper().removeprefix("AS")
    if not s.isdigit():
        raise ValueError("AS number must be a positive integer.")
    n = int(s)
    if n < 1 or n > 4_294_967_295:
        raise ValueError("AS number must be a positive integer.")
    return str(n)


def validate_certificate_hash(value: str) -> str:
    """Certificate fingerprint — SHA-1 (40 hex) or SHA-256 (64 hex).

    Accepts input with ':' separators (standard fingerprint display format)
    and whitespace; returns lowercase hex with separators stripped.
    """
    v = value.strip().replace(":", "").replace(" ", "").lower()
    if not (_HEX_40.match(v) or _HEX_64.match(v)):
        raise ValueError(
            "Enter a SHA-1 (40 hex) or SHA-256 (64 hex) certificate fingerprint."
        )
    return v


def validate_scope_row_value(scope_type: str, value: str) -> str:
    """Dispatch a scope-type-appropriate validator and return the canonical value string.

    Supported scope_type values (must match ScopeType enum in models/projects.py):
      ip_range    -> CIDR (IPv4 or IPv6) parsed by ipaddress.ip_network
      domain      -> FQDN per RFC 1035
      as_number   -> ASN, 1..4294967295
      certificate -> SHA-1 or SHA-256 hex digest
      keyword     -> free text (trimmed only — used in plainto_tsquery downstream)
      service     -> free text (trimmed only)
      whois       -> free text (trimmed only)
    """
    match scope_type:
        case "ip_range":
            return validate_cidr(value)
        case "domain":
            return validate_fqdn(value)
        case "as_number":
            return validate_as_number(value)
        case "certificate":
            return validate_certificate_hash(value)
        case "keyword" | "service" | "whois":
            return value.strip()
        case _:
            raise ValueError(f"unsupported scope_type: {scope_type}")
