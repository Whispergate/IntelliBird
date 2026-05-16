"""STIX intrusion-set → threat_actors upsert writer."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.actors import ThreatActor

logger = logging.getLogger(__name__)


def _mitre_group_id(obj: dict[str, Any]) -> str | None:
    """Return the MITRE ATT&CK group ID (e.g. 'G0016') from external_references."""
    for ref in obj.get("external_references") or []:
        if ref.get("source_name") == "mitre-attack":
            return ref.get("external_id")
    return None


def _iter_intrusion_sets(bundle: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield non-revoked, non-deprecated intrusion-set objects from a STIX bundle."""
    for obj in bundle.get("objects") or []:
        if obj.get("type") != "intrusion-set":
            continue
        if obj.get("revoked") or obj.get("x_mitre_deprecated"):
            continue
        yield obj


def upsert_actors_sync(bundle: dict[str, Any], matrix: str) -> int:  # noqa: ARG001
    """Upsert threat_actors from a STIX bundle. Returns count of rows processed.

    ON CONFLICT (mitre_group_id) updates aliases and last_bootstrap_at only.
    profile_md is intentionally excluded from the SET clause — analyst edits
    are preserved across re-bootstraps.

    Objects without a mitre_group_id are inserted with no ON CONFLICT clause
    (plain INSERT with on_conflict_do_nothing to avoid duplicate primary-key errors).
    """
    from app.config import settings  # lazy import — avoids circular deps at module load

    # Convert asyncpg DSN → psycopg DSN for sync use (mirrors attack_writer.py)
    url = settings.DATABASE_URL.replace("+asyncpg", "")
    engine = create_engine(url, future=True)
    count = 0
    with Session(engine) as session:
        for obj in _iter_intrusion_sets(bundle):
            group_id = _mitre_group_id(obj)
            values: dict[str, Any] = {
                "primary_name": obj["name"],
                "aliases": obj.get("aliases") or [],
                "mitre_group_id": group_id,
                "last_bootstrap_at": text("now()"),
                # profile_md seeded only on first insert — NOT refreshed on re-bootstrap
                "profile_md": obj.get("description"),
            }
            stmt = pg_insert(ThreatActor.__table__).values(**values)
            if group_id:
                # Partial unique index requires index_where to match ON CONFLICT resolution.
                stmt = stmt.on_conflict_do_update(
                    index_elements=["mitre_group_id"],
                    index_where=ThreatActor.__table__.c.mitre_group_id.isnot(None),
                    set_={
                        "aliases": stmt.excluded.aliases,
                        "last_bootstrap_at": stmt.excluded.last_bootstrap_at,
                        # NOTE: profile_md intentionally excluded — preserves analyst edits
                    },
                )
            else:
                # No conflict target available — use do_nothing to avoid PK collision
                stmt = stmt.on_conflict_do_nothing()
            session.execute(stmt)
            count += 1
        session.commit()
    engine.dispose()
    logger.info("upserted %d threat_actors from bundle", count)
    return count
