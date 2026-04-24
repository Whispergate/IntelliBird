"""Allowlist-based promotion of EASM findings to canonical events (EASM-06 / H-4).

Only high-confidence finding types reach the main /api/events feed. Low-confidence
types stay in easm_findings and the EASM namespace only. The /api/events default
filter excludes source_type='bbot' unless include_bbot=true — see plan 11-05 router.

Survival contract: events.easm_scan_id is ON DELETE SET NULL (migration 010); when
a scan is pruned by the 5-scan retention sweep, promoted events keep their row and
the "BBOT / <scan date>" badge falls back to "BBOT (historical scan)" in the UI.

PITFALLS §Pitfall 6: BBOT event 'data' field is polymorphic — dict for
FINDING/VULNERABILITY/TECHNOLOGY, str for DNS_NAME/IP_ADDRESS/URL.
All access to raw_bbot['data'] goes through _extract_data_fields() which uses
isinstance(data, dict) guard before any key access.
"""
from __future__ import annotations

import datetime
import uuid
from typing import Any

import stix2

from app.models.easm import EASMFinding, EASMScan

PROMOTION_ALLOWLIST: frozenset[str] = frozenset({
    "VULNERABILITY",
    "SUBDOMAIN_TAKEOVER_CANDIDATE",
    "TECHNOLOGY",
})

# FINDING is a special case — requires severity HIGH or CRITICAL
FINDING_MIN_SEVERITY: frozenset[str] = frozenset({"HIGH", "CRITICAL"})

# Low-confidence types for explicit rejection documentation:
_NON_PROMOTED_TYPES: frozenset[str] = frozenset({"DNS_NAME", "IP_ADDRESS", "OPEN_PORT", "URL"})

# STIX type assigned to the canonical events.stix_type column per BBOT event type
STIX_TYPE_BY_BBOT_TYPE: dict[str, str] = {
    "VULNERABILITY": "vulnerability",
    "TECHNOLOGY": "observed-data",
    "SUBDOMAIN_TAKEOVER_CANDIDATE": "indicator",
    "FINDING": "indicator",
}


def should_promote(bbot_event_type: str, severity: str | None) -> bool:
    """Return True iff this BBOT finding qualifies for canonical events promotion.

    Allowlist check (H-4 feed contamination prevention):
    - VULNERABILITY, SUBDOMAIN_TAKEOVER_CANDIDATE, TECHNOLOGY → always promote
    - FINDING → promote only when severity is HIGH or CRITICAL
    - DNS_NAME, IP_ADDRESS, OPEN_PORT, URL → never promote (stay in easm_findings)
    """
    if bbot_event_type in PROMOTION_ALLOWLIST:
        return True
    if bbot_event_type == "FINDING":
        return (severity or "").upper() in FINDING_MIN_SEVERITY
    return False


def _extract_data_fields(raw_bbot: dict[str, Any]) -> tuple[dict, str | None, str]:
    """Safely extract (data_dict, severity_or_none, description_or_target).

    PITFALLS §Pitfall 6: BBOT event 'data' field is polymorphic — dict for
    FINDING/VULNERABILITY/TECHNOLOGY, str for DNS_NAME/IP_ADDRESS/URL.
    Never assume dict.
    """
    data = raw_bbot.get("data", {})
    if isinstance(data, dict):
        severity = data.get("severity")
        description = data.get("description", "") or ""
        return data, severity, description
    # data is a plain string (DNS_NAME, IP_ADDRESS, URL shape)
    return {}, None, str(data or "")


def _build_stix_object(
    finding: EASMFinding,
    data: dict,
    now: datetime.datetime,
) -> Any:
    """Build a stix2 SDO/SCO appropriate to the BBOT event type.

    Returns the stix2 object — caller reads .id and .serialize().
    """
    target = finding.canonical_target
    t = finding.bbot_event_type

    if t == "VULNERABILITY":
        return stix2.Vulnerability(
            name=(data.get("description") or target)[:256],
            description=data.get("description", ""),
            external_references=[
                {
                    "source_name": "bbot",
                    "url": data.get("url", "") or "",
                }
            ],
            labels=["bbot-discovered"],
        )

    if t == "TECHNOLOGY":
        software = stix2.Software(
            name=data.get("technology", target),
            version=data.get("version"),
        )
        return stix2.ObservedData(
            first_observed=now,
            last_observed=now,
            number_observed=1,
            object_refs=[software.id],
        )

    if t == "SUBDOMAIN_TAKEOVER_CANDIDATE":
        return stix2.Indicator(
            name=f"Subdomain takeover: {target}",
            pattern=f"[domain-name:value = '{target}']",
            pattern_type="stix",
            valid_from=now,
            labels=["takeover-candidate"],
            custom_properties={
                "x_intellibird_takeover": True,
                "x_intellibird_target": target,
            },
        )

    # FINDING — only promoted when severity is HIGH or CRITICAL
    return stix2.Indicator(
        name=(data.get("description") or target)[:256],
        pattern=f"[domain-name:value = '{target}']",
        pattern_type="stix",
        valid_from=now,
        labels=["bbot-finding", (finding.severity or "unknown").lower()],
    )


def promote_finding_to_event(finding: EASMFinding, scan: EASMScan) -> dict[str, Any]:
    """Build a kwargs dict representing a canonical events row for this finding.

    Caller (worker / integration test) pops 'source_type' and other non-ORM keys
    before passing to Event() or _persist_event(), since events has no source_type
    column (source provenance for BBOT events is carried by easm_scan_id).

    Does NOT write to DB — pure function.

    Raises ValueError when the finding type is not in the promotion allowlist
    (caller should have checked should_promote() first).
    """
    if not should_promote(finding.bbot_event_type, finding.severity):
        raise ValueError(
            f"Finding {finding.id} ({finding.bbot_event_type}/{finding.severity}) "
            f"is not promotable — type not in allowlist or FINDING severity below threshold"
        )

    now = datetime.datetime.now(datetime.timezone.utc)
    raw_bbot = finding.raw_bbot if isinstance(finding.raw_bbot, dict) else {}
    data, _severity, _description = _extract_data_fields(raw_bbot)
    stix_obj = _build_stix_object(finding, data, now)
    stix_type = STIX_TYPE_BY_BBOT_TYPE[finding.bbot_event_type]

    return {
        # Provenance — note: events has no source_type column; this key is for
        # callers who need to know the feed type (e.g. H-4 feed-exclusion logic).
        # Workers must pop 'source_type' before passing to Event(**kwargs).
        "source_type": "bbot",
        # Event ORM columns:
        "stix_type": stix_type,
        "stix_id": stix_obj.id,
        "raw_stix": stix_obj.serialize(),
        "project_id": finding.project_id,
        "easm_scan_id": scan.id,
        "observed_at": now,
        "content_hash": finding.content_hash,
        "title": (data.get("description") or finding.canonical_target)[:256],
        "summary": (
            data.get("description", "")[:1024]
            if isinstance(data.get("description"), str)
            else ""
        ),
    }
