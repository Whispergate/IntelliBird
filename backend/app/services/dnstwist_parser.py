"""dnstwist JSON parser - defensive key access + derived lookup_success.

Key shape locked by docs/research/dnstwist-key-verification.md (dnstwist 20250130):
- Canonical domain key = `domain` (single form; NOT domain-name / domain_name in this version).
- DNS record keys snake_case: dns_a, dns_aaaa, dns_mx, dns_ns.
- `lookup_success` is NOT emitted by dnstwist - parser derives it as:
      has_a  = dns_a  non-empty AND dns_a[0]  not in {"!ServFail", ""}
      has_ns = dns_ns non-empty AND dns_ns[0] not in {"!ServFail", ""}
      lookup_success = has_a OR has_ns
- `!ServFail` sentinel + empty-string are both treated as "no data".

Defensive hyphen/underscore fallback on the domain key + snake/hyphen on DNS keys
is retained as cheap insurance against future version drift (per key-verification
Resolution section).
"""
from __future__ import annotations

from typing import Any

# Values that indicate "DNS lookup returned no usable data".
_NO_DATA_SENTINELS: frozenset[str] = frozenset({"!ServFail", ""})

# Fuzzer label that indicates the ORIGINAL unmodified input - skip.
_ORIGINAL_FUZZER: str = "*original"


def _get_domain(perm: dict[str, Any]) -> str | None:
    """Return the domain value, falling back across hyphen/underscore variants."""
    return (
        perm.get("domain")
        or perm.get("domain-name")
        or perm.get("domain_name")
    )


def _get_dns_list(perm: dict[str, Any], record: str) -> list[str]:
    """Return a DNS-record list (dns_a, dns_aaaa, dns_mx, dns_ns) with hyphen fallback."""
    snake = f"dns_{record}"
    hyphen = f"dns-{record}"
    value = perm.get(snake) or perm.get(hyphen) or []
    # dnstwist always emits lists; defensive coerce just in case.
    if not isinstance(value, list):
        return []
    return value


def _has_usable_records(records: list[str]) -> bool:
    """True if `records` has at least one entry that is not a no-data sentinel."""
    for entry in records:
        if entry not in _NO_DATA_SENTINELS:
            return True
    return False


def parse_permutation(perm: dict[str, Any]) -> dict[str, Any] | None:
    """Parse one dnstwist permutation row.

    Returns None when:
    - row has no domain key, or
    - row has NO DNS record keys at all (unregistered permutation).

    Returns a normalised dict with lowercased matched_value + derived lookup_success.
    """
    domain = _get_domain(perm)
    if not domain:
        return None

    dns_a = _get_dns_list(perm, "a")
    dns_aaaa = _get_dns_list(perm, "aaaa")
    dns_mx = _get_dns_list(perm, "mx")
    dns_ns = _get_dns_list(perm, "ns")

    # Filter fully-unregistered rows - no DNS record keys whatsoever.
    if not (dns_a or dns_aaaa or dns_mx or dns_ns):
        return None

    has_a = _has_usable_records(dns_a)
    has_ns = _has_usable_records(dns_ns)
    lookup_success = has_a or has_ns

    return {
        "matched_value": domain.lower(),
        "fuzzer": perm.get("fuzzer"),
        "dns_a": dns_a,
        "dns_aaaa": dns_aaaa,
        "dns_mx": dns_mx,
        "dns_ns": dns_ns,
        "lookup_success": lookup_success,
    }


def parse_dnstwist_output(json_payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse a full dnstwist --format json output list.

    - Skips the `*original` row (the unmodified input).
    - Skips unregistered rows (no DNS record keys at all).
    - Derives lookup_success for each emitted row.
    """
    out: list[dict[str, Any]] = []
    for perm in json_payload:
        if perm.get("fuzzer") == _ORIGINAL_FUZZER:
            continue
        parsed = parse_permutation(perm)
        if parsed is not None:
            out.append(parsed)
    return out
