"""Integration: poll_nvd end-to-end. Uses nvd_cve_sample.json + testcontainers PG.

nvdlib.searchCVE_V2 is monkeypatched to yield the fixture CVE — we are NOT
testing nvdlib itself, we are testing that OUR pipeline writes the correct
three rows (events + cve_details + attack_technique_tags) and advances the
cursor correctly.
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]
FIXTURE = BACKEND_DIR / "tests" / "fixtures" / "nvd_cve_sample.json"


def _ns(d):
    if isinstance(d, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in d.items()})
    if isinstance(d, list):
        return [_ns(x) for x in d]
    return d


@pytest.fixture(scope="module")
def live_db():
    with PostgresContainer("intellibird-db:m1") as pg:
        url = pg.get_connection_url()
        from sqlalchemy.engine import make_url
        parsed_url = make_url(url)
        asyncpg_url = (
            f"postgresql+asyncpg://{parsed_url.username}:{parsed_url.password}"
            f"@{parsed_url.host}:{parsed_url.port}/{parsed_url.database}"
        )
        env = os.environ | {
            "DATABASE_URL": asyncpg_url,
            "SECRET_KEY": "x" * 48,
            "REDIS_URL": "redis://localhost:1",
        }
        r = subprocess.run(["uv", "run", "alembic", "upgrade", "head"],
                           cwd=str(BACKEND_DIR), env=env, capture_output=True, text=True)
        if r.returncode != 0:
            pytest.skip(f"alembic failed: {r.stderr[:500]}")
        sync_url = (
            f"postgresql://{parsed_url.username}:{parsed_url.password}"
            f"@{parsed_url.host}:{parsed_url.port}/{parsed_url.database}"
        )
        engine = create_engine(sync_url, future=True)
        yield engine, env
        engine.dispose()


@pytest.fixture()
def nvd_source_id(live_db):
    engine, _ = live_db
    sid = uuid.uuid4()
    with Session(engine) as s:
        s.execute(text("""
            INSERT INTO sources (id, name, feed_type, url, poll_interval_sec)
            VALUES (:id, 'nvd-fixture', 'nvd', 'https://services.nvd.nist.gov/', 86400)
        """), {"id": str(sid)})
        s.commit()
    return sid


def _fixture_cve():
    raw = json.loads(FIXTURE.read_text())
    return _ns(raw["vulnerabilities"][0]["cve"])


def test_nvd_poll_end_to_end_from_fixture(live_db, nvd_source_id,
                                          monkeypatch: pytest.MonkeyPatch):
    engine, env = live_db
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app.config import Settings
    monkeypatch.setattr("app.config.settings", Settings())  # type: ignore[call-arg]

    from app.workers import nvd as nvd_module
    monkeypatch.setattr(nvd_module.nvdlib, "searchCVE_V2",
                        lambda **kw: iter([_fixture_cve()]))
    monkeypatch.setattr(nvd_module.time, "sleep", lambda s: None)

    nvd_module.poll_nvd_impl(str(nvd_source_id))

    with Session(engine) as s:
        events = s.execute(
            text("""SELECT id, title, raw_reference, content_hash, observed_at
                     FROM events WHERE source_id = :sid"""),
            {"sid": str(nvd_source_id)},
        ).all()
        assert len(events) == 1, events
        event_id = events[0].id
        assert events[0].title == "CVE-2024-99999"

        cvd = s.execute(
            text("""SELECT cve_id, cvss_v3_score, cwe_ids
                     FROM cve_details WHERE event_id = :eid"""),
            {"eid": str(event_id)},
        ).one()
        assert cvd.cve_id == "CVE-2024-99999"
        assert cvd.cvss_v3_score == 9.8
        assert cvd.cwe_ids == ["CWE-89"]

        tags = s.execute(
            text("""SELECT technique_id, tag_source, evidence_text
                     FROM attack_technique_tags WHERE event_id = :eid"""),
            {"eid": str(event_id)},
        ).all()
        assert len(tags) == 1
        assert tags[0].technique_id == "T1190"
        assert tags[0].tag_source == "feed_asserted"
        assert tags[0].evidence_text == "https://attack.mitre.org/techniques/T1190/"

        cursor = s.execute(
            text("SELECT last_cursor FROM sources WHERE id = :id"),
            {"id": str(nvd_source_id)},
        ).scalar()
        # 2026-04-10T12:00:00.000 + 1 second
        assert cursor is not None
        cur_dt = datetime.fromisoformat(cursor.replace("Z", "+00:00"))
        assert cur_dt == datetime(2026, 4, 10, 12, 0, 1, tzinfo=timezone.utc)


def test_nvd_poll_dedup_on_refetch(live_db, nvd_source_id,
                                   monkeypatch: pytest.MonkeyPatch):
    engine, env = live_db
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app.config import Settings
    monkeypatch.setattr("app.config.settings", Settings())  # type: ignore[call-arg]

    from app.workers import nvd as nvd_module
    monkeypatch.setattr(nvd_module.nvdlib, "searchCVE_V2",
                        lambda **kw: iter([_fixture_cve()]))
    monkeypatch.setattr(nvd_module.time, "sleep", lambda s: None)

    nvd_module.poll_nvd_impl(str(nvd_source_id))
    nvd_module.poll_nvd_impl(str(nvd_source_id))

    with Session(engine) as s:
        event_rows = s.execute(
            text("SELECT id FROM events WHERE source_id = :sid"),
            {"sid": str(nvd_source_id)},
        ).all()
        assert len(event_rows) == 1
        event_id = event_rows[0].id

        cvd_count = s.execute(
            text("SELECT count(*) FROM cve_details WHERE event_id = :eid"),
            {"eid": str(event_id)},
        ).scalar()
        tag_count = s.execute(
            text("SELECT count(*) FROM attack_technique_tags WHERE event_id = :eid"),
            {"eid": str(event_id)},
        ).scalar()
        assert cvd_count == 1
        assert tag_count == 1


def test_nvd_poll_health_on_success(live_db, nvd_source_id,
                                    monkeypatch: pytest.MonkeyPatch):
    engine, env = live_db
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app.config import Settings
    monkeypatch.setattr("app.config.settings", Settings())  # type: ignore[call-arg]

    from app.workers import nvd as nvd_module
    monkeypatch.setattr(nvd_module.nvdlib, "searchCVE_V2",
                        lambda **kw: iter([_fixture_cve()]))
    monkeypatch.setattr(nvd_module.time, "sleep", lambda s: None)

    nvd_module.poll_nvd_impl(str(nvd_source_id))

    with Session(engine) as s:
        row = s.execute(
            text("""SELECT last_polled_at, last_status, consecutive_failures
                     FROM sources WHERE id = :id"""),
            {"id": str(nvd_source_id)},
        ).one()
        assert row.last_polled_at is not None
        assert row.last_status == "ok"
        assert row.consecutive_failures == 0
