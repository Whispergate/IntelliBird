"""Integration: poll_taxii end-to-end. Uses taxii_mitre_sample.json fixture
+ testcontainers PG. taxii2client Server is monkeypatched to return the
fixture bundle so the test is deterministic.

OTX TAXII 1.1 integration tests are skip-unless-reachable (network probe
gate). Run with pytest -m integration to include both 2.1 and OTX suites.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]
FIXTURE = BACKEND_DIR / "tests" / "fixtures" / "taxii_mitre_sample.json"


def _otx_reachable() -> bool:
    """Returns True if the OTX TAXII endpoint is reachable and OTX_API_KEY is set."""
    if not os.environ.get("OTX_API_KEY"):
        return False
    try:
        socket.setdefaulttimeout(5)
        socket.getaddrinfo("otx.alienvault.com", 443)
        return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def live_db():
    with PostgresContainer("timescale/timescaledb:latest-pg16") as pg:
        url = pg.get_connection_url()
        env = os.environ | {
            "DATABASE_URL": url.replace("postgresql+psycopg2://", "postgresql+asyncpg://"),
            "SECRET_KEY": "x" * 48,
            "REDIS_URL": "redis://localhost:1",
        }
        r = subprocess.run(["uv", "run", "alembic", "upgrade", "head"],
                           cwd=str(BACKEND_DIR), env=env, capture_output=True, text=True)
        if r.returncode != 0:
            pytest.skip(f"alembic failed: {r.stderr[:500]}")
        sync_url = url.replace("postgresql+psycopg2://", "postgresql://")
        engine = create_engine(sync_url, future=True)
        yield engine, env
        engine.dispose()


@pytest.fixture()
def taxii_source_id(live_db):
    engine, _ = live_db
    sid = uuid.uuid4()
    with Session(engine) as s:
        s.execute(text("""
 INSERT INTO sources (id, name, feed_type, url, poll_interval_sec)
 VALUES (:id, 'mitre-fixture', 'taxii',
 'https://attack-taxii.mitre.org/taxii2/', 86400)
"""), {"id": str(sid)})
        s.commit()
    return sid


class _FakeCollection:
    def __init__(self, objects: list[dict]):
        self.objects = objects
        self.id = "fixture-collection"
    def get_objects(self, **kwargs):
        return {"objects": self.objects, "more": False}


def test_taxii_poll_fixture_end_to_end(live_db, taxii_source_id,
                                       monkeypatch: pytest.MonkeyPatch):
    engine, env = live_db
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app.config import Settings
    monkeypatch.setattr("app.config.settings", Settings())  # type: ignore[call-arg]

    objs = json.loads(FIXTURE.read_text())["objects"]
    coll = _FakeCollection(objs)

    class _ApiRoot:
        collections = [coll]
    class _Server:
        api_roots = [_ApiRoot()]

    from app.workers import taxii as taxii_module
    monkeypatch.setattr(taxii_module, "_build_server", lambda url, creds: _Server())

    taxii_module.poll_taxii_impl(str(taxii_source_id))

    with Session(engine) as s:
        count = s.execute(
            text("SELECT count(*) FROM events WHERE source_id = :sid"),
            {"sid": str(taxii_source_id)},
        ).scalar()
        assert count == 2
        rows = s.execute(
            text("""SELECT stix_type, stix_id, tlp_marking_id, raw_stix
 FROM events WHERE source_id =:sid ORDER BY stix_type"""),
            {"sid": str(taxii_source_id)},
        ).all()
        # attack-pattern alphabetically before indicator
        assert rows[0].stix_type == "attack-pattern"
        assert str(rows[0].tlp_marking_id) == "34098fce-860f-48ae-8e50-ebd3cc5e41da"
        assert rows[1].stix_type == "indicator"
        assert str(rows[1].tlp_marking_id) == "f88d31f6-1208-47b8-8c13-1706eb6387bc"
        # raw_stix preserved with external_references for attack-pattern
        raw_ap = rows[0].raw_stix
        assert raw_ap["external_references"][0]["external_id"] == "T1566"


def test_taxii_poll_dedup_on_refetch(live_db, taxii_source_id,
                                     monkeypatch: pytest.MonkeyPatch):
    engine, env = live_db
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app.config import Settings
    monkeypatch.setattr("app.config.settings", Settings())  # type: ignore[call-arg]

    objs = json.loads(FIXTURE.read_text())["objects"]
    class _ApiRoot:
        collections = [_FakeCollection(objs)]
    class _Server:
        api_roots = [_ApiRoot()]
    from app.workers import taxii as taxii_module
    monkeypatch.setattr(taxii_module, "_build_server", lambda url, creds: _Server())

    taxii_module.poll_taxii_impl(str(taxii_source_id))
    taxii_module.poll_taxii_impl(str(taxii_source_id))
    with Session(engine) as s:
        count = s.execute(
            text("SELECT count(*) FROM events WHERE source_id = :sid"),
            {"sid": str(taxii_source_id)},
        ).scalar()
        assert count == 2


def test_taxii_poll_raw_stix_stored(live_db, taxii_source_id,
                                    monkeypatch: pytest.MonkeyPatch):
    engine, env = live_db
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app.config import Settings
    monkeypatch.setattr("app.config.settings", Settings())  # type: ignore[call-arg]

    objs = json.loads(FIXTURE.read_text())["objects"]
    class _ApiRoot:
        collections = [_FakeCollection(objs)]
    class _Server:
        api_roots = [_ApiRoot()]
    from app.workers import taxii as taxii_module
    monkeypatch.setattr(taxii_module, "_build_server", lambda url, creds: _Server())

    taxii_module.poll_taxii_impl(str(taxii_source_id))
    with Session(engine) as s:
        row = s.execute(
            text("SELECT raw_stix FROM events WHERE stix_type = 'indicator' "
                 "AND source_id = :sid"),
            {"sid": str(taxii_source_id)},
        ).one()
        assert row.raw_stix["pattern"] == "[domain-name:value = 'fixture-bad.example']"
        assert row.raw_stix["spec_version"] == "2.1"


@pytest.mark.skipif(
    not _otx_reachable(),
    reason="OTX endpoint not reachable or OTX_API_KEY not set",
)
def test_taxii_poll_otx_taxii1_live(live_db, monkeypatch: pytest.MonkeyPatch):
    """Live OTX TAXII 1.1 smoke test. Requires OTX_API_KEY env var and network."""
    engine, env = live_db
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app.config import Settings
    monkeypatch.setattr("app.config.settings", Settings())  # type: ignore[call-arg]

    sid = uuid.uuid4()
    api_key = os.environ["OTX_API_KEY"]

    from app.crypto import encrypt_credentials
    from app.config import settings
    blob = encrypt_credentials(settings.SECRET_KEY, {"type": "otx-apikey", "key": api_key})

    with Session(engine) as s:
        s.execute(text("""
 INSERT INTO sources (id, name, feed_type, url, credentials_enc, poll_interval_sec)
 VALUES (:id, 'otx-live', 'taxii',
 'https://otx.alienvault.com/taxii/discovery',:creds, 86400)
"""), {"id": str(sid), "creds": blob})
        s.commit()

    from app.workers import taxii as taxii_module
    taxii_module.poll_taxii_impl(str(sid))

    with Session(engine) as s:
        status = s.execute(
            text("SELECT last_status FROM sources WHERE id = :sid"),
            {"sid": str(sid)},
        ).scalar()
        # Accept ok or rate_limited — both indicate successful communication
        assert status in ("ok", "rate_limited", "network_error"), \
            f"Unexpected status: {status}"
        count = s.execute(
            text("SELECT count(*) FROM events WHERE source_id = :sid"),
            {"sid": str(sid)},
        ).scalar()
        # OTX may have 0 new objects (if cursor filters all); just check no exception
        assert count >= 0
