"""AGE graph sync service — ENRICH-08.

Merges :DomainPivot vertices and :SHARES_INFRA edges into intellibird_graph
after WHOIS + passive DNS enrichment completes for a domain IOC.

Security:
  - Every DomainPivot MERGE includes project_id as a vertex property.
    This is the primary cross-project isolation guarantee; the WHERE predicate
    in traverse queries is a second line of defence.
  - Cypher string values are sanitized before f-string interpolation.
    AGE does not support $1 parameterised Cypher (only outside $$...$$).
  - SHARES_INFRA edges are only merged between DomainPivot nodes with the
    SAME project_id — no cross-project edge is ever created.
"""
from __future__ import annotations

import logging
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_SAFE_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9._-]{1,253}$")
_SAFE_UUID_RE = re.compile(r"^[0-9a-f-]{36}$")


def _sanitize_domain(val: str) -> str:
    """Validate domain for safe Cypher interpolation."""
    if not _SAFE_DOMAIN_RE.match(val):
        raise ValueError(f"Unsafe domain for Cypher interpolation: {val!r}")
    return val


def _sanitize_uuid(val: str) -> str:
    """Validate UUID string for safe Cypher interpolation."""
    s = str(uuid.UUID(val))  # raises ValueError on malformed UUID
    if not _SAFE_UUID_RE.match(s):
        raise ValueError(f"Unsafe UUID for Cypher interpolation: {s!r}")
    return s


@asynccontextmanager
async def age_conn(session: AsyncSession) -> AsyncGenerator:
    """Set up AGE on the raw driver connection for this session."""
    raw = await session.connection()
    await raw.exec_driver_sql("LOAD 'age'")
    await raw.exec_driver_sql('SET search_path = ag_catalog, "$user", public')
    yield raw


async def _merge_domain_pivot(raw, domain: str, ioc_id: str, project_id: str) -> None:
    """MERGE :DomainPivot vertex with project_id property."""
    safe_domain = _sanitize_domain(domain)
    safe_ioc_id = _sanitize_uuid(ioc_id)
    safe_project_id = _sanitize_uuid(project_id)
    now = datetime.now(timezone.utc).isoformat()

    cypher = (
        f"MERGE (d:DomainPivot {{domain: '{safe_domain}', project_id: '{safe_project_id}'}}) "
        f"SET d.ioc_id = '{safe_ioc_id}', d.updated_at = '{now}'"
    )
    await raw.exec_driver_sql(
        f"SELECT * FROM cypher('intellibird_graph', $$ {cypher} $$) AS (r ag_catalog.agtype)"
    )


async def _merge_shares_infra(
    raw, domain_a: str, domain_b: str, reason: str, project_id: str
) -> None:
    """MERGE :SHARES_INFRA edge between two DomainPivot nodes in same project."""
    safe_a = _sanitize_domain(domain_a)
    safe_b = _sanitize_domain(domain_b)
    safe_pid = _sanitize_uuid(project_id)
    # Sanitize reason: only alphanumeric + underscore
    safe_reason = re.sub(r"[^a-zA-Z0-9_]", "_", reason)[:64]

    cypher = (
        f"MATCH (a:DomainPivot {{domain: '{safe_a}', project_id: '{safe_pid}'}}) "
        f"MATCH (b:DomainPivot {{domain: '{safe_b}', project_id: '{safe_pid}'}}) "
        f"MERGE (a)-[:SHARES_INFRA {{reason: '{safe_reason}'}}]->(b)"
    )
    await raw.exec_driver_sql(
        f"SELECT * FROM cypher('intellibird_graph', $$ {cypher} $$) AS (r ag_catalog.agtype)"
    )


async def _find_sibling_domains_sql(
    session: AsyncSession, domain: str, project_id: str
) -> list[tuple[str, str]]:
    """Find other domain IOCs in the same project that share registrar, email, or historical IP.

    Returns list of (sibling_domain, reason) tuples.
    reason is one of: 'shared_registrar', 'shared_email', 'shared_ip'

    Cross-project isolation: all SQL queries filter by i.project_id = :pid so that
    only DomainPivot nodes within the same project are considered for SHARES_INFRA edges.
    """
    pid = uuid.UUID(project_id)  # validate
    siblings: list[tuple[str, str]] = []

    # Get WHOIS data for the seed domain
    seed_row = (
        await session.execute(
            text(
                "SELECT registrar, registrant_email FROM whois_cache WHERE domain = :domain"
            ),
            {"domain": domain},
        )
    ).mappings().first()

    if seed_row is None:
        return siblings

    # Match on registrar (non-NULL)
    if seed_row["registrar"]:
        rows = (
            await session.execute(
                text(
                    "SELECT wc.domain FROM whois_cache wc "
                    "JOIN iocs i ON i.normalized_value = wc.domain "
                    "WHERE i.project_id = :pid "
                    "  AND i.type = 'domain' "
                    "  AND wc.domain != :domain "
                    "  AND wc.registrar = :registrar "
                    "  AND wc.registrar IS NOT NULL "
                    "LIMIT 50"
                ),
                {"pid": pid, "domain": domain, "registrar": seed_row["registrar"]},
            )
        ).fetchall()
        siblings.extend((row[0], "shared_registrar") for row in rows)

    # Match on registrant_email (non-NULL)
    if seed_row["registrant_email"]:
        rows = (
            await session.execute(
                text(
                    "SELECT wc.domain FROM whois_cache wc "
                    "JOIN iocs i ON i.normalized_value = wc.domain "
                    "WHERE i.project_id = :pid "
                    "  AND i.type = 'domain' "
                    "  AND wc.domain != :domain "
                    "  AND wc.registrant_email = :email "
                    "  AND wc.registrant_email IS NOT NULL "
                    "LIMIT 50"
                ),
                {"pid": pid, "domain": domain, "email": seed_row["registrant_email"]},
            )
        ).fetchall()
        siblings.extend((row[0], "shared_email") for row in rows)

    # Match on shared historical IP
    rows = (
        await session.execute(
            text(
                "SELECT DISTINCT i2.normalized_value FROM passive_dns_records p1 "
                "JOIN iocs i1 ON i1.id = p1.ioc_id AND i1.normalized_value = :domain "
                "JOIN passive_dns_records p2 ON p2.ip = p1.ip AND p2.ioc_id != p1.ioc_id "
                "JOIN iocs i2 ON i2.id = p2.ioc_id AND i2.project_id = :pid "
                "   AND i2.type = 'domain' AND i2.normalized_value != :domain "
                "LIMIT 50"
            ),
            {"pid": pid, "domain": domain},
        )
    ).fetchall()
    siblings.extend((row[0], "shared_ip") for row in rows)

    # Deduplicate keeping first reason
    seen: dict[str, str] = {}
    for sib_domain, reason in siblings:
        if sib_domain not in seen:
            seen[sib_domain] = reason
    return list(seen.items())


async def sync_domain_pivot(
    session: AsyncSession,
    ioc_id: str,
    domain: str,
    project_id: str,
) -> None:
    """Full AGE sync for one domain IOC after enrichment completes.

    1. MERGE :DomainPivot vertex (with project_id property).
    2. Find sibling domains in same project sharing registrar/email/IP.
    3. Ensure sibling DomainPivot nodes exist (MERGE).
    4. MERGE :SHARES_INFRA edges.

    All edges are project-scoped — no cross-project edges created.
    AGE errors are caught and logged without propagating to the caller so that
    a graph sync failure never fails the enrichment worker.
    """
    try:
        async with age_conn(session) as raw:
            await _merge_domain_pivot(raw, domain, ioc_id, project_id)

        # Find siblings via SQL (outside AGE connection — uses regular session)
        siblings = await _find_sibling_domains_sql(session, domain, project_id)

        if siblings:
            async with age_conn(session) as raw:
                for sib_domain, reason in siblings:
                    try:
                        # Ensure sibling vertex exists (MERGE is idempotent)
                        sib_ioc = (
                            await session.execute(
                                text(
                                    "SELECT id FROM iocs WHERE normalized_value = :domain "
                                    "AND project_id = :pid AND type = 'domain' LIMIT 1"
                                ),
                                {"domain": sib_domain, "pid": uuid.UUID(project_id)},
                            )
                        ).scalar_one_or_none()
                        if sib_ioc:
                            await _merge_domain_pivot(
                                raw, sib_domain, str(sib_ioc), project_id
                            )
                        await _merge_shares_infra(raw, domain, sib_domain, reason, project_id)
                    except ValueError as exc:
                        logger.warning(
                            "age_sync_skip sib_domain=%s error=%r", sib_domain, exc
                        )
                        continue

        logger.info(
            "age_sync_complete domain=%s project_id=%s edges=%d",
            domain,
            project_id,
            len(siblings),
        )
    except Exception as exc:  # noqa: BLE001
        # AGE sync failure must NOT fail the enrichment worker — log and continue.
        logger.error("age_sync_error domain=%s error=%r", domain, exc)


__all__ = ["sync_domain_pivot", "age_conn", "_sanitize_domain", "_sanitize_uuid"]
