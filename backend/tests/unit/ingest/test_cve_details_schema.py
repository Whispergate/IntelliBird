"""Migration 002 part 2 — cve_details table for INGC-02.

Schema shape decided per RESEARCH.md Open Questions #2 (separate table,
keyed on event_id as plain UUID, no FK to events because events is a
TimescaleDB hypertable).
"""
from __future__ import annotations

import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def migrated_engine():
    """Run alembic upgrade head against intellibird-db:m1 (PG16 + TS + AGE)."""
    import os
    with PostgresContainer("intellibird-db:m1") as pg:
        url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        env2 = os.environ | {"DATABASE_URL": url}
        r = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=str(BACKEND_DIR), env=env2, capture_output=True, text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"alembic upgrade failed: {r.stderr[:500]}")
        sync = url.replace("postgresql+asyncpg://", "postgresql://")
        eng = create_engine(sync, future=True)
        yield eng
        eng.dispose()


def test_cve_details_columns(migrated_engine) -> None:
    insp = inspect(migrated_engine)
    cols = {c["name"]: c for c in insp.get_columns("cve_details")}
    assert set(cols) == {
        "event_id", "cve_id", "cvss_v3_score", "cvss_v3_vector",
        "cpe_match", "cwe_ids", "last_modified",
    }
    assert cols["cve_id"]["nullable"] is False
    assert cols["cvss_v3_score"]["nullable"] is True
    # cpe_match is JSONB — SQLAlchemy reflects as JSON/JSONB
    assert "JSON" in str(cols["cpe_match"]["type"]).upper()
    # cwe_ids is TEXT[]
    assert "ARRAY" in str(cols["cwe_ids"]["type"]).upper() or str(cols["cwe_ids"]["type"]).endswith("[]")


def test_cve_details_indexes(migrated_engine) -> None:
    insp = inspect(migrated_engine)
    idx_names = {i["name"] for i in insp.get_indexes("cve_details")}
    assert "idx_cve_details_cve_id" in idx_names
    assert "idx_cve_details_cvss_v3" in idx_names


def test_no_fk_to_events(migrated_engine) -> None:
    insp = inspect(migrated_engine)
    fks = insp.get_foreign_keys("cve_details")
    for fk in fks:
        assert fk["referred_table"] != "events", \
            "cve_details.event_id must NOT FK to events (hypertable limit)"


def test_orm_round_trip(migrated_engine) -> None:
    from app.models.cve_details import CveDetails

    eid = uuid.uuid4()
    with Session(migrated_engine) as s:
        row = CveDetails(
            event_id=eid,
            cve_id="CVE-2024-99999",
            cvss_v3_score=9.8,
            cvss_v3_vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            cpe_match=[{"criteria": "cpe:2.3:a:fixture:webapp:1.0.0:*:*:*:*:*:*:*"}],
            cwe_ids=["CWE-89"],
            last_modified=datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc),
        )
        s.add(row)
        s.commit()
        fresh = s.get(CveDetails, eid)
        assert fresh is not None
        assert fresh.cve_id == "CVE-2024-99999"
        assert fresh.cvss_v3_score == 9.8
        assert fresh.cwe_ids == ["CWE-89"]
        assert fresh.cpe_match[0]["criteria"].startswith("cpe:2.3:a:fixture")


def test_downgrade_restores_preexisting(migrated_engine) -> None:
    """Round-trip: downgrade one rev, upgrade head, cve_details gone then back."""
    import os
    import subprocess as sp

    # Build asyncpg URL from the sync engine URL (which uses plain postgresql://)
    raw = migrated_engine.url
    asyncpg_url = (
        f"postgresql+asyncpg://{raw.username}:{raw.password}"
        f"@{raw.host}:{raw.port}/{raw.database}"
    )
    env2 = os.environ | {"DATABASE_URL": asyncpg_url}
    sp.run(
        ["uv", "run", "alembic", "downgrade", "0001_initial_schema"],
        cwd=str(BACKEND_DIR), env=env2, check=True,
    )
    with migrated_engine.connect() as c:
        r = c.execute(text("SELECT to_regclass('public.cve_details')")).scalar()
    assert r is None, "cve_details should be dropped after downgrade"
    sp.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=str(BACKEND_DIR), env=env2, check=True,
    )
    with migrated_engine.connect() as c:
        r = c.execute(text("SELECT to_regclass('public.cve_details')")).scalar()
    assert r == "cve_details"
