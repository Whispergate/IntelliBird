"""
— YARA engine: in-memory sample scan and STIX pattern extraction scan.
SECURITY: No temp files written. All YARA scanning is in-process bytes matching.
"""
from __future__ import annotations
import io
import logging
import re
import uuid
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

# Regex patterns to extract indicator values from STIX pattern strings
_SHA256_RE = re.compile(r"file:hashes\.'SHA-256'\s*=\s*'([a-fA-F0-9]{64})'")
_SHA1_RE = re.compile(r"file:hashes\.'SHA-1'\s*=\s*'([a-fA-F0-9]{40})'")
_MD5_RE = re.compile(r"file:hashes\.'MD5'\s*=\s*'([a-fA-F0-9]{32})'")
_IP_RE = re.compile(r"ipv4-addr[^']*value\s*=\s*'([0-9.]+)'")
_DOMAIN_RE = re.compile(r"domain-name[^']*value\s*=\s*'([^']+)'")
_STIX_SCAN_META = "stix_pattern_scan"


async def scan_sample(
    db: AsyncSession,
    project_id: uuid.UUID | None,
    sample_data: bytes,
) -> list[dict]:
    """
    Scan sample bytes against all enabled YARA rules scoped to project_id or global.
    Returns list of {rule_id, rule_name, family} dicts for each matching rule.
    Never raises — yara.Error per rule is logged and skipped.
    """
    import yara  # Import deferred so module is importable without libyara installed
    rules_rows = await _load_active_rules(db, project_id, stix_only=False)
    matches = []
    for row in rules_rows:
        try:
            compiled = _load_compiled(row)
            hits = compiled.match(data=sample_data)
            if hits:
                matches.append({
                    "rule_id": str(row.id),
                    "rule_name": row.name,
                    "family": row.family,
                })
        except Exception as exc:
            log.warning("yara_scan_error rule_id=%s error=%r", row.id, exc)
    return matches


async def scan_stix_pattern(
    db: AsyncSession,
    project_id: uuid.UUID | None,
    stix_pattern_str: str,
) -> list[dict]:
    """
    Extract indicator values from STIX pattern string and scan against rules
    that have stix_pattern_scan: true metadata.
    Returns list of {rule_id, rule_name, family} dicts.
    """
    import yara
    # Only load rules that have the stix_pattern_scan metadata flag in their content
    rules_rows = await _load_active_rules(db, project_id, stix_only=True)
    if not rules_rows:
        return []
    # Extract indicator values from STIX pattern string
    indicator_values = _extract_stix_values(stix_pattern_str)
    if not indicator_values:
        return []
    matches = []
    for row in rules_rows:
        try:
            compiled = _load_compiled(row)
            for value in indicator_values:
                hits = compiled.match(data=value.encode())
                if hits:
                    matches.append({
                        "rule_id": str(row.id),
                        "rule_name": row.name,
                        "family": row.family,
                    })
                    break  # one match per rule is sufficient
        except Exception as exc:
            log.warning("yara_stix_scan_error rule_id=%s error=%r", row.id, exc)
    return matches


async def write_yara_matches(
    db: AsyncSession,
    rule_matches: list[dict],
    event_id: uuid.UUID,
    scan_context: str = "sample",
) -> None:
    """
    Persist yara_matches rows for each rule match.
    Also calls attack_technique_tags insert with tag_source='auto' for rule family.
    Uses ON CONFLICT DO NOTHING for idempotency.
    """
    for match in rule_matches:
        await db.execute(
            text("""
                INSERT INTO yara_matches (id, rule_id, event_id, matched_at, scan_context)
                VALUES (gen_random_uuid(), :rule_id, :event_id, now(), :scan_context)
                ON CONFLICT (rule_id, event_id, scan_context) DO NOTHING
            """),
            {
                "rule_id": match["rule_id"],
                "event_id": str(event_id),
                "scan_context": scan_context,
            },
        )
    # Auto-tag event with rule family using attack_technique_tag pattern
    # Use family as a pseudo-technique_id; tag_source='auto' is the valid enum value
    for match in rule_matches:
        if match.get("family"):
            await db.execute(
                text("""
                    INSERT INTO attack_technique_tags (event_id, technique_id, tag_source, evidence_text)
                    VALUES (:event_id, :technique_id, 'auto', :evidence)
                    ON CONFLICT DO NOTHING
                """),
                {
                    "event_id": str(event_id),
                    "technique_id": match["family"],
                    "evidence": f"YARA rule: {match['rule_name']}",
                },
            )


def _extract_stix_values(pattern: str) -> list[str]:
    """Extract raw indicator values from a STIX pattern string."""
    values = []
    for regex in (_SHA256_RE, _SHA1_RE, _MD5_RE, _IP_RE, _DOMAIN_RE):
        values.extend(regex.findall(pattern))
    return values


async def _load_active_rules(
    db: AsyncSession,
    project_id: uuid.UUID | None,
    stix_only: bool = False,
) -> list:
    """Load enabled YARA rules: global (project_id IS NULL) + project-scoped."""
    from app.models.yara_rules import YaraRule
    stmt = select(YaraRule).where(YaraRule.enabled == True)  # noqa: E712
    if project_id is not None:
        stmt = stmt.where(
            (YaraRule.project_id == project_id) | (YaraRule.project_id.is_(None))
        )
    if stix_only:
        stmt = stmt.where(YaraRule.content.contains(_STIX_SCAN_META))
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _load_compiled(row) -> "yara.Rules":
    """Load compiled YARA rules from cache or compile from source."""
    import yara
    if row.compiled_cache:
        return yara.load(file=io.BytesIO(row.compiled_cache))
    return yara.compile(source=row.content)
