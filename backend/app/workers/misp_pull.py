"""MISP pull worker - MISP-02, MISP-04.

Sync module (PyMISP uses requests, not httpx).
Called by misp_pull_job_wrapper() from scheduler/jobs.py.

MISP-02: Pull attributes matching pull_tags → upsert into iocs table.
MISP-04: Pull galaxy clusters of type 'threat-actor' → upsert into threat_actors table.
Dedup: mitre_group_id first (when not None), then primary_name exact match.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

log = logging.getLogger(__name__)

# Attribute type mapping: MISP type → IOC type (from CONTEXT.md locked decisions)
_MISP_TO_IOC_TYPE: dict[str, str] = {
    "ip-src": "ip",
    "ip-dst": "ip",
    "domain": "domain",
    "hostname": "domain",
    "md5": "hash",
    "sha256": "hash",
    "sha1": "sha1",
    "url": "url",
    "email-src": "email",
    "email-dst": "email",
}

# Regex to extract ATT&CK group ID from MITRE refs (e.g. "https://attack.mitre.org/groups/G0016/")
_MITRE_GROUP_RE = re.compile(r"attack\.mitre\.org/groups/(G\d{4})", re.IGNORECASE)


def _misp_type_to_ioc_type(misp_type: str) -> str | None:
    """Map a MISP attribute type to an IntelliBird IOC type. Returns None to skip."""
    return _MISP_TO_IOC_TYPE.get(misp_type)


def _build_ioc_dict(*, misp_type: str, value: str, project_id: str | UUID) -> dict:
    """Build an IOC dict from a MISP attribute. Returns dict or None if type unknown."""
    ioc_type = _misp_type_to_ioc_type(misp_type)
    if ioc_type is None:
        return {}
    return {
        "type": ioc_type,
        "normalized_value": value.lower().strip(),
        "raw_value": value,
        "project_id": str(project_id),
        "source": "misp",
        "confidence": 0.7,
    }


def _extract_mitre_group_id(refs: list[str]) -> str | None:
    """Extract MITRE ATT&CK group ID from a list of reference URLs."""
    for ref in refs:
        m = _MITRE_GROUP_RE.search(ref)
        if m:
            return m.group(1)
    return None


def _should_insert_actor(
    cluster: dict[str, Any],
    existing: list[dict[str, Any]],
) -> bool:
    """Return True if this cluster should be inserted (no dedup match found).

    Dedup strategy (CONTEXT.md locked):
    1. If cluster.mitre_group_id is not None → match on mitre_group_id
    2. Else → match on exact primary_name
    """
    cluster_mitre = cluster.get("mitre_group_id")
    cluster_name = cluster.get("primary_name", "")

    for row in existing:
        if cluster_mitre is not None:
            if row.get("mitre_group_id") == cluster_mitre:
                return False
        else:
            # Both None: fall back to primary_name exact match
            if row.get("mitre_group_id") is None and row.get("primary_name") == cluster_name:
                return False
    return True


def _pull_attributes(misp: Any, pull_tags: list[str], project_id: str) -> list[dict]:
    """Pull attributes from MISP matching pull_tags. Returns list of IOC dicts."""
    ioc_dicts: list[dict] = []
    for tag in pull_tags:
        try:
            attrs = misp.search_attributes(tags=[tag], pythonify=True)
            for attr in attrs:
                d = _build_ioc_dict(
                    misp_type=attr.type,
                    value=attr.value,
                    project_id=project_id,
                )
                if d:
                    ioc_dicts.append(d)
        except Exception as exc:  # noqa: BLE001
            log.warning("misp_attribute_pull_failed tag=%s error=%s", tag, exc)
    return ioc_dicts


def _upsert_iocs_sync(ioc_dicts: list[dict], project_id: str) -> int:
    """Upsert IOC rows into the iocs table via sync psycopg2. Returns insert count."""
    if not ioc_dicts:
        return 0
    import psycopg2  # noqa: PLC0415
    from app.config import settings  # noqa: PLC0415

    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://").replace("+asyncpg", "")
    conn = psycopg2.connect(db_url)
    inserted = 0
    try:
        with conn.cursor() as cur:
            for ioc in ioc_dicts:
                cur.execute(
                    """
                    INSERT INTO iocs
                      (type, normalized_value, raw_value, project_id, source, confidence)
                    VALUES
                      (%(type)s, %(normalized_value)s, %(raw_value)s,
                       %(project_id)s, 'misp', %(confidence)s)
                    ON CONFLICT (type, normalized_value, project_id) DO UPDATE
                      SET last_seen = now(),
                          source = EXCLUDED.source
                    """,
                    ioc,
                )
                if cur.rowcount:
                    inserted += 1
        conn.commit()
    finally:
        conn.close()
    return inserted


def _sync_galaxy_clusters(misp: Any, project_id: str) -> int:
    """Pull threat-actor galaxy clusters and upsert into threat_actors. Returns insert count."""
    import psycopg2  # noqa: PLC0415
    from app.config import settings  # noqa: PLC0415

    try:
        galaxy = misp.get_galaxy(galaxy="threat-actor", withCluster=True, pythonify=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("misp_galaxy_pull_failed error=%s", exc)
        return 0

    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://").replace("+asyncpg", "")
    conn = psycopg2.connect(db_url)
    inserted = 0
    try:
        with conn.cursor() as cur:
            # Load existing actors for dedup
            cur.execute("SELECT primary_name, mitre_group_id FROM threat_actors")
            existing = [{"primary_name": r[0], "mitre_group_id": r[1]} for r in cur.fetchall()]

            for cluster in getattr(galaxy, "GalaxyCluster", []):
                meta = cluster.meta or {}
                refs = meta.get("refs", [])
                mitre_id = _extract_mitre_group_id(refs)
                cluster_dict = {
                    "primary_name": cluster.value,
                    "mitre_group_id": mitre_id,
                }
                if not _should_insert_actor(cluster_dict, existing):
                    continue
                aliases = meta.get("synonyms", []) or []
                cur.execute(
                    """
                    INSERT INTO threat_actors (primary_name, aliases, mitre_group_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (mitre_group_id) WHERE mitre_group_id IS NOT NULL
                    DO UPDATE SET aliases = EXCLUDED.aliases
                    """,
                    (cluster.value, aliases or None, mitre_id),
                )
                existing.append(cluster_dict)
                inserted += 1
        conn.commit()
    finally:
        conn.close()
    return inserted


def misp_pull_job_wrapper(project_id: str, misp_config: dict) -> None:
    """Sync APScheduler job wrapper. PyMISP is blocking HTTP - runs in sync context.

    Args:
        project_id: UUID string of the project.
        misp_config: dict with keys: url, api_key_enc, pull_tags, push_types, enabled, ssl_verify.
    """
    from pymisp import PyMISP  # noqa: PLC0415
    from app.crypto import decrypt_credentials  # noqa: PLC0415
    from app.config import settings  # noqa: PLC0415

    if not misp_config.get("enabled", False):
        log.debug("misp_pull_skipped project_id=%s reason=disabled", project_id)
        return

    try:
        creds = decrypt_credentials(settings.SECRET_KEY, misp_config["api_key_enc"])
    except Exception as exc:  # noqa: BLE001
        log.error("misp_credential_decrypt_failed project_id=%s error=%s", project_id, exc)
        return

    try:
        misp = PyMISP(
            url=misp_config["url"],
            key=creds["api_key"],
            ssl=misp_config.get("ssl_verify", True),
        )
    except Exception as exc:  # noqa: BLE001
        log.error("misp_connect_failed project_id=%s error=%s", project_id, exc)
        return

    pull_tags = misp_config.get("pull_tags", [])
    ioc_dicts = _pull_attributes(misp, pull_tags, project_id)
    n_iocs = _upsert_iocs_sync(ioc_dicts, project_id)
    log.info("misp_pull_complete project_id=%s iocs_upserted=%d", project_id, n_iocs)

    n_actors = _sync_galaxy_clusters(misp, project_id)
    log.info("misp_galaxy_sync_complete project_id=%s actors_inserted=%d", project_id, n_actors)


__all__ = [
    "_misp_type_to_ioc_type",
    "_build_ioc_dict",
    "_should_insert_actor",
    "_extract_mitre_group_id",
    "misp_pull_job_wrapper",
]
