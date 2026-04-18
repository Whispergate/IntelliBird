"""Backfill actor idempotency tests — plan 06-02 (MAP-05).

Tests verify:
- backfill_geo_once_impl resolves STIX-location events and UPDATEs geo cols
- events without usable geo data are skipped
- events already with geo_lat set are excluded by the SELECT predicate
- second run produces zero UPDATEs (idempotent)
"""
from __future__ import annotations

import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# STIX bundles for seeding
# ---------------------------------------------------------------------------

_STIX_WITH_LOCATION = {
    "type": "bundle",
    "id": "bundle--geo-test",
    "objects": [
        {
            "type": "location",
            "id": "location--paris",
            "latitude": 48.85,
            "longitude": 2.35,
            "country": "FR",
        }
    ],
}

_STIX_NO_GEO = {
    "type": "bundle",
    "id": "bundle--no-geo-test",
    "objects": [
        {
            "type": "malware",
            "id": "malware--xyz",
            "name": "TestMalware",
            "is_family": False,
        }
    ],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def live_db():
    """Start intellibird-db:m1, run alembic upgrade head, yield (engine, env)."""
    with PostgresContainer("intellibird-db:m1") as pg:
        url = pg.get_connection_url()
        parsed = make_url(url)
        asyncpg_url = (
            f"postgresql+asyncpg://{parsed.username}:{parsed.password}"
            f"@{parsed.host}:{parsed.port}/{parsed.database}"
        )
        env = os.environ | {
            "DATABASE_URL": asyncpg_url,
            "SECRET_KEY": "x" * 48,
            "REDIS_URL": "redis://localhost:1",
            # Point to a non-existent MMDB so MaxMind path is disabled;
            # tests rely on STIX location SDO path only.
            "GEOLITE_PATH": "/tmp/nonexistent_geolite.mmdb",
        }
        r = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"alembic failed: {r.stderr[:500]}")
        sync_url = (
            f"postgresql://{parsed.username}:{parsed.password}"
            f"@{parsed.host}:{parsed.port}/{parsed.database}"
        )
        engine = create_engine(sync_url, future=True)
        yield engine, env
        engine.dispose()


def _insert_source(engine) -> uuid.UUID:
    sid = uuid.uuid4()
    with Session(engine) as s:
        s.execute(
            text("""
                INSERT INTO sources (id, name, feed_type, url, poll_interval_sec, enabled,
                                     hot_retention_days, archive_policy)
                VALUES (:id, :name, 'rss', :url, 3600, true, 30, 'keep')
            """),
            {
                "id": str(sid),
                "name": f"backfill-test-{sid}",
                "url": f"http://fixture/backfill/{sid}",
            },
        )
        s.commit()
    return sid


def _insert_event(
    engine,
    *,
    source_id: uuid.UUID,
    raw_stix: dict | None = None,
    geo_lat: float | None = None,
    geo_lon: float | None = None,
    content_hash: str | None = None,
) -> uuid.UUID:
    eid = uuid.uuid4()
    if content_hash is None:
        content_hash = str(uuid.uuid4())
    with Session(engine) as s:
        s.execute(
            text("""
                INSERT INTO events
                    (id, source_id, stix_type, observed_at, content_hash,
                     raw_stix, geo_lat, geo_lon, archived)
                VALUES
                    (:id, :sid, 'indicator', now(), :ch,
                     :raw_stix::jsonb, :geo_lat, :geo_lon, false)
            """),
            {
                "id": str(eid),
                "sid": str(source_id),
                "ch": content_hash,
                "raw_stix": __import__("json").dumps(raw_stix) if raw_stix else None,
                "geo_lat": geo_lat,
                "geo_lon": geo_lon,
            },
        )
        s.commit()
    return eid


def _apply_env(monkeypatch: pytest.MonkeyPatch, env: dict) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import importlib
    import app.config as cfg_module
    importlib.reload(cfg_module)
    monkeypatch.setattr("app.config.settings", cfg_module.settings)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_backfill_resolves_and_updates(live_db, monkeypatch):
    """Backfill resolves STIX-location events and skips non-resolvable / pre-populated ones."""
    engine, env = live_db
    _apply_env(monkeypatch, env)

    # Reset geo module state so the missing MMDB warning fires fresh
    import app.services.geo as geo_module
    geo_module._reader = None
    geo_module._reader_attempted = False
    geo_module._lookup_ip.cache_clear()

    source_id = _insert_source(engine)

    # Event 1: has STIX location SDO — should be updated by backfill
    eid_with_location = _insert_event(
        engine,
        source_id=source_id,
        raw_stix=_STIX_WITH_LOCATION,
    )

    # Event 2: has STIX but no geo-resolvable SDO — should stay NULL
    eid_no_geo = _insert_event(
        engine,
        source_id=source_id,
        raw_stix=_STIX_NO_GEO,
    )

    # Event 3: already has geo_lat/geo_lon — excluded by SELECT predicate
    eid_already_resolved = _insert_event(
        engine,
        source_id=source_id,
        raw_stix=_STIX_WITH_LOCATION,
        geo_lat=99.0,
        geo_lon=99.0,
    )

    from app.services.geo_backfill import backfill_geo_once_impl

    result = backfill_geo_once_impl()

    assert result["updated"] >= 1, f"Expected at least 1 update, got {result}"

    with Session(engine) as s:
        row1 = s.execute(
            text("SELECT geo_lat, geo_lon, country_code FROM events WHERE id = :id"),
            {"id": str(eid_with_location)},
        ).one()
        row2 = s.execute(
            text("SELECT geo_lat, geo_lon FROM events WHERE id = :id"),
            {"id": str(eid_no_geo)},
        ).one()
        row3 = s.execute(
            text("SELECT geo_lat, geo_lon FROM events WHERE id = :id"),
            {"id": str(eid_already_resolved)},
        ).one()

    # Event 1: resolved
    assert row1.geo_lat == pytest.approx(48.85), f"Expected 48.85, got {row1.geo_lat}"
    assert row1.geo_lon == pytest.approx(2.35), f"Expected 2.35, got {row1.geo_lon}"
    assert row1.country_code == "FR"

    # Event 2: unresolvable — stays NULL
    assert row2.geo_lat is None, f"Expected None, got {row2.geo_lat}"
    assert row2.geo_lon is None

    # Event 3: was excluded by SELECT predicate — coords unchanged
    assert row3.geo_lat == pytest.approx(99.0)
    assert row3.geo_lon == pytest.approx(99.0)


def test_backfill_is_idempotent(live_db, monkeypatch):
    """Running backfill_geo_once_impl a second time returns updated=0."""
    engine, env = live_db
    _apply_env(monkeypatch, env)

    # Reset geo module state
    import app.services.geo as geo_module
    geo_module._reader = None
    geo_module._reader_attempted = False
    geo_module._lookup_ip.cache_clear()

    # First pass (may have been run already by previous test — that's fine)
    from app.services.geo_backfill import backfill_geo_once_impl

    backfill_geo_once_impl()

    # Second pass — all previously-resolvable rows already have geo_lat set
    result2 = backfill_geo_once_impl()

    assert result2["updated"] == 0, (
        f"Expected 0 updates on second run (idempotent), got {result2['updated']}"
    )
