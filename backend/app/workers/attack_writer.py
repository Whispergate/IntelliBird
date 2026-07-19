"""Extract and upsert ATT&CK technique rows from a STIX 2.1 bundle."""
from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

# app.config imported lazily inside upsert_techniques_sync to avoid a
# module-load dependency on (broker/ and config/
# run in the same wave; their order is undefined).
from app.models.attack import AttackTechnique

logger = logging.getLogger(__name__)


def _technique_id_from_stix(obj: dict) -> str | None:
    for ref in obj.get("external_references", []) or []:
        if ref.get("source_name") == "mitre-attack":
            return ref.get("external_id")
    return None


def _iter_techniques(bundle: dict) -> Iterable[dict]:
    for obj in bundle.get("objects", []) or []:
        if obj.get("type") != "attack-pattern":
            continue
        if obj.get("revoked") or obj.get("x_mitre_deprecated"):
            continue
        if _technique_id_from_stix(obj):
            yield obj


def _tactic_from_stix(obj: dict) -> str | None:
    phases = obj.get("kill_chain_phases") or []
    for p in phases:
        if p.get("kill_chain_name") == "mitre-attack":
            return p.get("phase_name")
    return None


def upsert_techniques_sync(bundle: dict, matrix: str) -> int:
    """Synchronous upsert - called from Dramatiq actor (sync context).

 Uses a short-lived sync engine so it does not collide with the API's
 async engine. Returns the number of rows upserted.
"""
    from app.config import settings  # lazy import - see module docstring

    # Convert asyncpg DSN → psycopg DSN for sync use
    url = settings.DATABASE_URL.replace("+asyncpg", "")
    engine = create_engine(url, future=True)
    count = 0
    with Session(engine) as session:
        for obj in _iter_techniques(bundle):
            tid = _technique_id_from_stix(obj)
            if not tid:
                continue
            row = {
                "technique_id": tid,
                "name": obj.get("name") or tid,
                "tactic": _tactic_from_stix(obj),
                "description": obj.get("description"),
                "platform": obj.get("x_mitre_platforms") or None,
                "matrix": matrix,
                "stix_id": obj.get("id"),
                "raw_stix": obj,
            }
            stmt = pg_insert(AttackTechnique.__table__).values(**row)  # type: ignore[arg-type]
            stmt = stmt.on_conflict_do_update(
                index_elements=["technique_id"],
                set_={
                    "name": stmt.excluded.name,
                    "tactic": stmt.excluded.tactic,
                    "description": stmt.excluded.description,
                    "platform": stmt.excluded.platform,
                    "matrix": stmt.excluded.matrix,
                    "stix_id": stmt.excluded.stix_id,
                    "raw_stix": stmt.excluded.raw_stix,
                    "fetched_at": text("now()"),
                },
            )
            session.execute(stmt)
            count += 1
        session.commit()
    engine.dispose()
    return count
