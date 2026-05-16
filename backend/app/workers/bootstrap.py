"""ATT&CK catalog bootstrap actor. TAXII → GitHub → bundled JSON."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import dramatiq
import httpx
from taxii2client.v21 import Server

logger = logging.getLogger(__name__)

ATTACK_TAXII_URL = "https://attack-taxii.mitre.org/api/v21/"
ATTACK_GITHUB_BASE = "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master"
BUNDLED_PATH = Path(__file__).resolve().parent.parent / "bootstrap" / "attack"

TAXII_COLLECTIONS: dict[str, str] = {
    "enterprise": "x-mitre-collection--1f5f1533-f617-4ca8-9ab4-6a02367fa019",
    "ics":        "x-mitre-collection--90c00720-636b-4485-b342-8751d232bf09",
    "mobile":     "x-mitre-collection--dac0d2d7-8653-445c-9bff-82f934c1e858",
}

GITHUB_URLS: dict[str, str] = {
    "enterprise": f"{ATTACK_GITHUB_BASE}/enterprise-attack/enterprise-attack.json",
    "ics":        f"{ATTACK_GITHUB_BASE}/ics-attack/ics-attack.json",
    "mobile":     f"{ATTACK_GITHUB_BASE}/mobile-attack/mobile-attack.json",
}

BUNDLED_FILES: dict[str, Path] = {
    "enterprise": BUNDLED_PATH / "enterprise-attack.json",
    "ics":        BUNDLED_PATH / "ics-attack.json",
    "mobile":     BUNDLED_PATH / "mobile-attack.json",
}

MATRICES = ("enterprise", "ics", "mobile")


def _fetch_taxii(matrix: str, timeout: float = 30.0) -> dict | None:
    try:
        server = Server(ATTACK_TAXII_URL)
        for api_root in server.api_roots:
            for collection in api_root.collections:
                if collection.id == TAXII_COLLECTIONS[matrix]:
                    envelope = collection.get_objects()
                    return {"objects": list(envelope.get("objects", []))}
    except Exception as e:  # noqa: BLE001
        logger.warning("attack_taxii_failed matrix=%s error=%s", matrix, e)
    return None


def _fetch_github(matrix: str, timeout: float = 60.0) -> dict | None:
    try:
        resp = httpx.get(GITHUB_URLS[matrix], timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("attack_github_failed matrix=%s error=%s", matrix, e)
    return None


def _fetch_bundled(matrix: str) -> dict | None:
    path = BUNDLED_FILES[matrix]
    if path.exists():
        try:
            return json.loads(path.read_bytes())
        except Exception as e:  # noqa: BLE001
            logger.error("attack_bundled_parse_failed matrix=%s error=%s", matrix, e)
    return None


def fetch_with_fallback(matrix: str) -> dict | None:
    """Public helper — exposed for tests to monkeypatch individual steps."""
    for loader in (_fetch_taxii, _fetch_github, _fetch_bundled):
        bundle = loader(matrix)
        if bundle is not None:
            return bundle
    logger.error("attack_bootstrap_all_sources_failed matrix=%s", matrix)
    return None


@dramatiq.actor(max_retries=0, queue_name="maintenance")
def bootstrap_attack() -> None:
    """Fetch ATT&CK for all three matrices with fallback chain."""
    from app.workers.attack_writer import upsert_techniques_sync
    from app.workers.actor_writer import upsert_actors_sync

    for matrix in MATRICES:
        bundle = fetch_with_fallback(matrix)
        if bundle:
            count = upsert_techniques_sync(bundle, matrix)
            logger.info("attack_bootstrap_wrote matrix=%s count=%d", matrix, count)
            if matrix in ("enterprise", "ics"):
                actor_count = upsert_actors_sync(bundle, matrix)
                logger.info("bootstrap_attack: upserted %d actors matrix=%s", actor_count, matrix)
