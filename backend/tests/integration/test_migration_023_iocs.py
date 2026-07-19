"""IOC-01 migration 023 round-trip introspection tests.

Uses the PINNED `db_session` / `db_engine` fixtures from
backend/tests/integration/conftest.py - do NOT invent any other fixture name
(see IntelliBird MEMORY.md `project_test_pollution` warning).

`_migrations_applied` (autouse-by-dependency via `db_engine`) guarantees
`alembic upgrade head` has run before these tests execute.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_iocs_table_exists(db_session):
    result = await db_session.execute(
        text("SELECT to_regclass('public.iocs') IS NOT NULL AS ok")
    )
    assert result.scalar() is True


@pytest.mark.asyncio
async def test_ioc_event_links_table_exists(db_session):
    result = await db_session.execute(
        text("SELECT to_regclass('public.ioc_event_links') IS NOT NULL AS ok")
    )
    assert result.scalar() is True


@pytest.mark.asyncio
async def test_ioc_type_enum_exists_with_thirteen_values(db_session):
    result = await db_session.execute(
        text(
            "SELECT enumlabel FROM pg_enum e "
            "JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname = 'ioc_type_enum' "
            "ORDER BY e.enumsortorder"
        )
    )
    labels = [row[0] for row in result.fetchall()]
    assert labels == [
        "ip", "ipv6", "domain", "url",
        "sha256", "sha1", "md5",
        "email", "btc", "eth", "mutex", "registry_key", "filename",
    ]


@pytest.mark.asyncio
async def test_ioc_status_enum_exists(db_session):
    result = await db_session.execute(
        text(
            "SELECT enumlabel FROM pg_enum e "
            "JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname = 'ioc_status_enum' "
            "ORDER BY e.enumsortorder"
        )
    )
    labels = [row[0] for row in result.fetchall()]
    assert labels == ["active", "expired", "whitelisted"]


@pytest.mark.asyncio
async def test_ioc_source_enum_exists(db_session):
    result = await db_session.execute(
        text(
            "SELECT enumlabel FROM pg_enum e "
            "JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname = 'ioc_source_enum' "
            "ORDER BY e.enumsortorder"
        )
    )
    labels = [row[0] for row in result.fetchall()]
    assert labels == ["manual", "csv", "json", "stix", "event", "backfill"]


@pytest.mark.asyncio
async def test_uq_iocs_project_type_value_index_is_nulls_not_distinct(db_session):
    """The unique index supporting global-row dedup must be NULLS NOT DISTINCT
    so two (NULL, 'ip', '1.2.3.4') rows collide. pg_index.indnullsnotdistinct
    is the PG15+ flag exposing this.
    """
    result = await db_session.execute(
        text(
            "SELECT i.indnullsnotdistinct "
            "FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname = 'uq_iocs_project_type_value'"
        )
    )
    row = result.first()
    assert row is not None, "uq_iocs_project_type_value index missing"
    assert row[0] is True
