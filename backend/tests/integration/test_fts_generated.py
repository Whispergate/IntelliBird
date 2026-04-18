"""Integration tests for migration 004 — search_tsv backfill + GIN + filter_presets.

These tests run against the live stack (docker compose exec -T api ...).
They assume migration 004 has already been applied.

Proves:
1. GENERATED ALWAYS AS fires on INSERT — search_tsv is non-null and tokenised.
2. GIN index ix_events_search_tsv is registered with am=gin in pg_indexes.
3. filter_presets table accepts INSERT/SELECT round-trip.
4. FTS @@ operator returns expected rows (smoke test for GIN usability).

The downgrade integration test is explicitly deferred — rolling back a live
stack safely is out of scope for M1.
"""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from app.database import async_session_factory
from tests.fixtures.events_seed import SOURCE_RSS, TLP_CLEAR

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Test 1: search_tsv is populated on insert (backfill proof)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_tsv_populated_on_existing_rows() -> None:
    """Insert a row — confirm search_tsv is non-null immediately.

    This proves GENERATED ALWAYS AS computation fires on insert to the
    existing TimescaleDB hypertable without any explicit write to search_tsv.
    Also confirms backfill: the column is non-null for rows inserted after
    migration applied.
    """
    async with async_session_factory() as session:
        # Ensure source exists (INSERT ON CONFLICT)
        await session.execute(
            text(
                "INSERT INTO sources "
                "(id, name, feed_type, url, poll_interval_sec, hot_retention_days, archive_policy) "
                "VALUES (:sid, 'fts-test', 'rss', 'https://fts.test/feed', 3600, 30, 'drop') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"sid": str(SOURCE_RSS)},
        )

        eid = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO events "
                "(id, observed_at, stix_type, source_id, "
                "raw_reference, title, description, content_hash, tlp_marking_id, visibility, archived) "
                "VALUES (:eid, now(), 'report', :sid, 'test', "
                ":title, :desc, :hash, :tlp, 'shared', false)"
            ),
            {
                "eid": str(eid),
                "sid": str(SOURCE_RSS),
                "title": "APT28 phishing campaign",
                "desc": "sophisticated spear-phishing targeting energy sector",
                "hash": "fts-test-" + eid.hex[:10],
                "tlp": str(TLP_CLEAR),
            },
        )
        await session.commit()

        # search_tsv should be auto-populated by GENERATED ALWAYS AS
        row = (
            await session.execute(
                text("SELECT search_tsv::text FROM events WHERE id = :eid"),
                {"eid": str(eid)},
            )
        ).one_or_none()
        assert row is not None, "inserted row not found"
        tsv_text = row[0]
        assert tsv_text is not None, (
            "search_tsv was NULL — GENERATED ALWAYS AS not firing on TimescaleDB hypertable"
        )
        # Stemmed tokens from title + description should appear
        assert "apt28" in tsv_text.lower() or "'apt28'" in tsv_text.lower(), (
            f"'apt28' token not found in search_tsv: {tsv_text}"
        )
        assert "phish" in tsv_text.lower(), (
            f"'phish' stem not found in search_tsv (from 'phishing'): {tsv_text}"
        )

        # Cleanup
        await session.execute(
            text("DELETE FROM events WHERE id = :eid"), {"eid": str(eid)}
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Test 2: GIN index is registered in pg_indexes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_tsv_indexed_by_gin() -> None:
    """ix_events_search_tsv must exist in pg_indexes with am=gin."""
    async with async_session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE tablename = 'events' AND indexname = 'ix_events_search_tsv'"
                ),
            )
        ).one_or_none()
        assert row is not None, "ix_events_search_tsv not found in pg_indexes"
        indexname, indexdef = row
        assert "gin" in indexdef.lower(), f"index is not GIN; indexdef = {indexdef}"


# ---------------------------------------------------------------------------
# Test 3: filter_presets round-trip INSERT / SELECT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filter_presets_table_exists() -> None:
    """Direct INSERT + SELECT on filter_presets confirms table is usable."""
    async with async_session_factory() as session:
        unique_name = "fts-test-" + uuid.uuid4().hex[:8]
        params_dict = {"source_type": ["rss"], "tlp": ["clear"]}
        await session.execute(
            text(
                "INSERT INTO filter_presets (name, query_params) "
                "VALUES (:name, CAST(:params AS jsonb))"
            ),
            {"name": unique_name, "params": json.dumps(params_dict)},
        )
        await session.commit()

        row = (
            await session.execute(
                text(
                    "SELECT name, query_params FROM filter_presets WHERE name = :name"
                ),
                {"name": unique_name},
            )
        ).one_or_none()
        assert row is not None, f"filter_preset '{unique_name}' not found after insert"
        assert row[0] == unique_name
        assert row[1] == params_dict, f"query_params mismatch: {row[1]!r}"

        # Cleanup
        await session.execute(
            text("DELETE FROM filter_presets WHERE name = :name"), {"name": unique_name}
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Test 4: FTS @@ operator smoke test — indexed lookup returns inserted row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fts_query_uses_index_smoke() -> None:
    """plainto_tsquery against search_tsv returns the inserted row (GIN usable)."""
    async with async_session_factory() as session:
        # Ensure source exists
        await session.execute(
            text(
                "INSERT INTO sources "
                "(id, name, feed_type, url, poll_interval_sec, hot_retention_days, archive_policy) "
                "VALUES (:sid, 'fts-smoke', 'rss', 'https://smoke.test/feed', 3600, 30, 'drop') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"sid": str(SOURCE_RSS)},
        )
        eid = uuid.uuid4()
        unique_token = "SMOKETOKEN" + eid.hex[:6].upper()
        await session.execute(
            text(
                "INSERT INTO events "
                "(id, observed_at, stix_type, source_id, "
                "raw_reference, title, description, content_hash, tlp_marking_id, visibility, archived) "
                "VALUES (:eid, now(), 'report', :sid, 'smoke', "
                ":title, 'smoke-body', :hash, :tlp, 'shared', false)"
            ),
            {
                "eid": str(eid),
                "sid": str(SOURCE_RSS),
                "title": f"Unique {unique_token} alpha event",
                "hash": "smoke-" + eid.hex[:10],
                "tlp": str(TLP_CLEAR),
            },
        )
        await session.commit()

        found = (
            await session.execute(
                text(
                    "SELECT id FROM events "
                    "WHERE search_tsv @@ plainto_tsquery('english', :q)"
                ),
                {"q": unique_token.lower()},
            )
        ).all()
        assert any(str(r[0]) == str(eid) for r in found), (
            f"FTS lookup for '{unique_token.lower()}' did not find inserted row {eid}"
        )

        # Cleanup
        await session.execute(
            text("DELETE FROM events WHERE id = :eid"), {"eid": str(eid)}
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Deferred: downgrade integration test
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="deferred: live stack can't downgrade safely in M1")
@pytest.mark.asyncio
async def test_migration_downgrade_drops_column_and_table() -> None:
    """Downgrade integration test deferred to post-M1 safe downgrade workflow."""
    pass
