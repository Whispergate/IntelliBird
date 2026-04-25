"""Integration: poll_html_scrape end-to-end against fixture HTML + live PG.

Quick task 260425-ovt:
  - INSERT a Source with feed_type='custom' + scrape_config.
  - Monkeypatch fetch_html so the test never hits the network or filesystem.
  - Invoke poll_html_scrape_impl directly (NOT via Dramatiq dispatch).
  - Assert events landed, dedup absorbs a second poll, ingest_stats row exists.

Mirrors the testcontainer harness used by test_rss_poll.py 1:1.
"""
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parents[2]
FIXTURE = BACKEND_DIR / "tests" / "fixtures" / "html_scrape_checkpoint.html"
SOURCE_URL = "https://research.checkpoint.com/"


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
            "JWT_SIGNING_KEY": "j" * 64,
            "REDIS_URL": "redis://localhost:1",
        }
        r = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=str(BACKEND_DIR), env=env, capture_output=True, text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"alembic failed (AGE missing likely): {r.stderr[:400]}")
        sync_url = (
            f"postgresql://{parsed_url.username}:{parsed_url.password}"
            f"@{parsed_url.host}:{parsed_url.port}/{parsed_url.database}"
        )
        engine = create_engine(sync_url, future=True)
        yield engine, env
        engine.dispose()


@pytest.fixture()
def html_scrape_source_id(live_db):
    engine, _env = live_db
    sid = uuid.uuid4()
    scrape_config = {
        "item_selector": "article.post",
        "title_selector": "h2 a",
        "link_selector": "h2 a@href",
        "date_selector": "time@datetime",
        "summary_selector": ".excerpt",
        "max_items": 50,
    }
    with Session(engine) as s:
        s.execute(
            text(
                """
                INSERT INTO sources (id, name, feed_type, url, poll_interval_sec, scrape_config)
                VALUES (:id, 'checkpoint-fixture', 'custom', :url, 3600,
                        CAST(:cfg AS jsonb))
                """
            ),
            {"id": str(sid), "url": SOURCE_URL, "cfg": __import__("json").dumps(scrape_config)},
        )
        s.commit()
    return sid


def test_html_scrape_round_trip(live_db, html_scrape_source_id, monkeypatch: pytest.MonkeyPatch):
    engine, env = live_db
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app.config import Settings
    monkeypatch.setattr("app.config.settings", Settings())  # type: ignore[call-arg]

    fixture_html = FIXTURE.read_text(encoding="utf-8")

    def _fake_fetch_html(url: str, **_kw) -> str:
        assert url == SOURCE_URL
        return fixture_html

    monkeypatch.setattr(
        "app.ingest.html_scrape_parser.fetch_html", _fake_fetch_html
    )
    # The worker imports fetch_html into its own module namespace at import-time;
    # patch that binding too so the actor uses our fake.
    monkeypatch.setattr("app.workers.html_scrape.fetch_html", _fake_fetch_html)

    from app.workers.html_scrape import poll_html_scrape_impl
    poll_html_scrape_impl(str(html_scrape_source_id))

    with Session(engine) as s:
        rows = s.execute(
            text(
                """SELECT title, raw_reference, source_id, stix_type, content_hash
                   FROM events WHERE source_id = :sid ORDER BY observed_at"""
            ),
            {"sid": str(html_scrape_source_id)},
        ).all()
        assert len(rows) >= 3
        assert all(r.stix_type == "x-intellibird-html-scrape" for r in rows)
        assert all(r.title for r in rows)
        assert all(r.raw_reference.startswith("https://") for r in rows)
        assert all(r.content_hash for r in rows)

        first_count = len(rows)

    # Re-poll → dedup absorbs everything.
    poll_html_scrape_impl(str(html_scrape_source_id))
    with Session(engine) as s:
        count = s.execute(
            text("SELECT count(*) FROM events WHERE source_id = :sid"),
            {"sid": str(html_scrape_source_id)},
        ).scalar()
        assert count == first_count

        stats = s.execute(
            text(
                """SELECT parse_ok, parse_error, fetch_ok, fetch_error
                   FROM source_ingest_stats WHERE source_id = :sid"""
            ),
            {"sid": str(html_scrape_source_id)},
        ).all()
        assert stats, "expected at least one source_ingest_stats row"
        agg_parse_ok = sum(r.parse_ok for r in stats)
        agg_fetch_ok = sum(r.fetch_ok for r in stats)
        assert agg_fetch_ok >= 1
        assert agg_parse_ok >= 3
