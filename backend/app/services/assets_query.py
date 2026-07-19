"""Asset aggregation query builder.

Single-source-of-truth for:
  * build_assets_aggregation_select - GROUP BY on easm_findings
  * compute_asset_scope            - per-row scope dispatch (in/out/unscoped)
  * asset_id_for                   - stable synthetic id for URL paths
  * bucket_for_type                - summary-card type grouping
  * load_stale_cutoff              - MAX finished-scan started_at per project

Invariants:
  * Scope rows fetched ONCE per request (research Pitfall 2)
  * The raw finding payload column is NEVER pulled into list/summary (research Pitfall 1)
  * asset_id concatenation order is locked: bbot_event_type FIRST, canonical_target SECOND, no separator, UTF-8 (research Pitfall 4)
"""
from __future__ import annotations

import hashlib
import ipaddress
import uuid
from datetime import datetime
from typing import Final, Iterable

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.easm import EASMFinding, EASMScan
from app.models.projects import ProjectScopeRow
from app.schemas.assets import AssetScope, AssetSummaryBucket, SUMMARY_BUCKET_KEYS


# --- Type classification (UI-SPEC §Surface 3 + CONTEXT §Scope reconciliation) ---

DOMAIN_SCOPED_TYPES: Final[frozenset[str]] = frozenset({
    "DNS_NAME", "URL", "URL_UNVERIFIED", "HTTP_RESPONSE", "VHOST",
    # CONTEXT §Scope reconciliation: hostname-bearing finding types dispatch
    # through FQDN suffix matching - they are domain-scoped, not
    # unscoped-by-design.
    "SUBDOMAIN_TAKEOVER_CANDIDATE", "FINDING", "VULNERABILITY",
})
IP_SCOPED_TYPES: Final[frozenset[str]] = frozenset({"IP_ADDRESS"})
HYBRID_SCOPED_TYPES: Final[frozenset[str]] = frozenset({"OPEN_TCP_PORT", "OPEN_UDP_PORT"})

# CONTEXT §Scope reconciliation (authoritative): only TECHNOLOGY / EMAIL_ADDRESS
# / WAF / USERNAME are unscoped-by-v1-design. Other low-signal types that
# cannot be anchored to any scope row also land here. SUBDOMAIN_TAKEOVER_CANDIDATE,
# FINDING, VULNERABILITY are NOT included - they route through DOMAIN_SCOPED_TYPES.
UNSCOPED_BY_DESIGN: Final[frozenset[str]] = frozenset({
    "TECHNOLOGY", "EMAIL_ADDRESS", "USERNAME", "WAF",
    "HASHED_PASSWORD", "PASSWORD", "STORAGE_BUCKET", "MOBILE_APP",
    "SOCIAL", "ORG_STUB", "CODE_REPOSITORY", "FILESYSTEM",
    "ASN", "AZURE_TENANT", "PROTOCOL",
    "GEOLOCATION", "RAW_TEXT", "RAW_DNS_RECORD", "WEBSCREENSHOT",
    "WEB_PARAMETER", "URL_HINT", "DNS_NAME_UNRESOLVED", "IP_RANGE",
})

# UI-SPEC §Surface 3 locked groupings.
_BUCKET_MAP: Final[dict[str, str]] = {
    "DNS_NAME": "DOMAINS", "URL_HOSTNAME": "DOMAINS",
    "IP_ADDRESS": "IPS",
    "OPEN_TCP_PORT": "OPEN_PORTS", "OPEN_UDP_PORT": "OPEN_PORTS",
    "URL": "URLS", "URL_UNVERIFIED": "URLS",
    "TECHNOLOGY": "TECHNOLOGIES", "WAF": "TECHNOLOGIES",
    "EMAIL_ADDRESS": "IDENTITIES", "USERNAME": "IDENTITIES",
}


def bucket_for_type(bbot_event_type: str) -> str:
    """Map any BBOT event type to one of the 7 summary buckets (default OTHER)."""
    return _BUCKET_MAP.get(bbot_event_type, "OTHER")


def asset_id_for(bbot_event_type: str, canonical_target: str) -> str:
    """Deterministic sha256 hex digest used as URL-safe asset identifier.

    Locked order (research Pitfall 4): bbot_event_type FIRST, canonical_target
    SECOND, no separator, UTF-8 encoding. TypeScript client MUST mirror this
    exact concatenation.
    """
    payload = f"{bbot_event_type}{canonical_target}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# --- Scope dispatch (Python-side; scope rows fetched once per request) ---


def _extract_host_port(value: str) -> tuple[str, str | None]:
    """Split 'host:port' - returns (host, port_or_none).
    Handles IPv6 brackets if present ([::1]:443 -> ("::1", "443")).
    """
    if value.startswith("[") and "]" in value:
        host, _, rest = value.partition("]")
        host = host.lstrip("[")
        port = rest.lstrip(":") or None
        return host, port
    if ":" in value:
        host, _, port = value.rpartition(":")
        return host, port
    return value, None


def _matches_domain_row(target: str, row: ProjectScopeRow) -> bool:
    """Exact match OR proper-suffix match on FQDN."""
    target = target.strip().lower()
    rv = row.value.strip().lower()
    return target == rv or target.endswith(f".{rv}")


def _matches_ip_range_row(target: str, row: ProjectScopeRow) -> bool:
    try:
        addr = ipaddress.ip_address(target)
        net = ipaddress.ip_network(row.value, strict=False)
        return addr in net
    except (ValueError, TypeError):
        return False


def compute_asset_scope(
    bbot_event_type: str,
    canonical_target: str,
    scope_rows: Iterable[ProjectScopeRow],
) -> AssetScope:
    """Python-side scope dispatch - pure function, no I/O.

    Caller MUST fetch scope_rows once per request via
    project_scope.fetch_scope_rows_intel; this function iterates the cache.

    Rules:
      * UNSCOPED_BY_DESIGN types -> UNSCOPED (regardless of scope_rows)
      * DOMAIN_SCOPED_TYPES -> dispatch to scope_type='domain' rows via FQDN suffix
        (includes hostname-bearing finding types per CONTEXT §Scope reconciliation)
      * IP_SCOPED_TYPES     -> dispatch to scope_type='ip_range' rows via CIDR containment
      * HYBRID_SCOPED_TYPES -> parse host from 'host:port', then dispatch by host shape
      * No applicable rows   -> UNSCOPED
      * Exclude rows subtract matches (any exclude match flips in_scope -> out_of_scope)
    """
    if bbot_event_type in UNSCOPED_BY_DESIGN:
        return AssetScope.UNSCOPED

    scope_rows = list(scope_rows)

    host = canonical_target
    if bbot_event_type in HYBRID_SCOPED_TYPES:
        host, _ = _extract_host_port(canonical_target)

    if bbot_event_type in DOMAIN_SCOPED_TYPES:
        applicable = [r for r in scope_rows if r.scope_type == "domain"]
        matcher = _matches_domain_row
    elif bbot_event_type in IP_SCOPED_TYPES:
        applicable = [r for r in scope_rows if r.scope_type == "ip_range"]
        matcher = _matches_ip_range_row
    elif bbot_event_type in HYBRID_SCOPED_TYPES:
        try:
            ipaddress.ip_address(host)
            applicable = [r for r in scope_rows if r.scope_type == "ip_range"]
            matcher = _matches_ip_range_row
        except (ValueError, TypeError):
            applicable = [r for r in scope_rows if r.scope_type == "domain"]
            matcher = _matches_domain_row
    else:
        return AssetScope.UNSCOPED

    if not applicable:
        return AssetScope.UNSCOPED

    includes = [r for r in applicable if not r.exclude]
    excludes = [r for r in applicable if r.exclude]

    if not includes:
        return AssetScope.UNSCOPED

    any_include_match = any(matcher(host, r) for r in includes)
    any_exclude_match = any(matcher(host, r) for r in excludes)

    if any_include_match and not any_exclude_match:
        return AssetScope.IN_SCOPE
    return AssetScope.OUT_OF_SCOPE


# --- Aggregation SELECT + stale cutoff + summary serialisation ---


def build_assets_aggregation_select(project_id: uuid.UUID):
    """One row per (bbot_event_type, canonical_target) for the project.

    Emits columns:
        bbot_event_type, canonical_target,
        first_seen (MIN), last_seen (MAX),
        scan_count (COUNT DISTINCT scan_id),
        modules (array_agg DISTINCT module),
        severity_max (MAX severity)

    Does NOT pull the finding raw payload - that's drawer-only (Pitfall 1).
    """
    return (
        select(
            EASMFinding.bbot_event_type.label("bbot_event_type"),
            EASMFinding.canonical_target.label("canonical_target"),
            func.min(EASMFinding.first_seen).label("first_seen"),
            func.max(EASMFinding.last_seen).label("last_seen"),
            func.count(distinct(EASMFinding.scan_id)).label("scan_count"),
            func.array_agg(distinct(EASMFinding.module)).label("modules"),
            func.max(EASMFinding.severity).label("severity_max"),
        )
        .where(EASMFinding.project_id == project_id)
        .group_by(EASMFinding.bbot_event_type, EASMFinding.canonical_target)
    )


async def load_stale_cutoff(
    session: AsyncSession, project_id: uuid.UUID
) -> datetime | None:
    """Return MAX(easm_scans.started_at WHERE status='finished' AND project_id=X)."""
    stmt = (
        select(func.max(EASMScan.started_at))
        .where(EASMScan.project_id == project_id)
        .where(EASMScan.status == "finished")
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def summary_from_rows(
    rows: Iterable[dict],
) -> dict[str, AssetSummaryBucket]:
    """Reduce aggregation rows (each with bbot_event_type + stale bool) to per-bucket counts.

    Every SUMMARY_BUCKET_KEYS member appears in output even when zero -
    UI-SPEC §Surface 3 locks stable 7-card layout.
    """
    counts = {k: 0 for k in SUMMARY_BUCKET_KEYS}
    stale_counts = {k: 0 for k in SUMMARY_BUCKET_KEYS}
    for row in rows:
        bucket = bucket_for_type(row["bbot_event_type"])
        counts[bucket] += 1
        if row.get("stale"):
            stale_counts[bucket] += 1
    return {
        k: AssetSummaryBucket(count=counts[k], stale_count=stale_counts[k])
        for k in SUMMARY_BUCKET_KEYS
    }
