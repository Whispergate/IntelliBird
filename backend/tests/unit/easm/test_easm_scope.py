"""Unit tests for easm_scope.py - EASM-02 scope consumption.

Activated by plan 11-02 (was Wave 0 stub referencing plan 11-04).

These tests use an in-memory async SQLite approach via aiosqlite so they run
without a live Postgres container. The ProjectScopeRow ORM is exercised via
SQLAlchemy's async session against a create_all'd schema.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

os.environ.setdefault("SECRET_KEY", "x" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "y" * 64)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base  # noqa: F401
import app.models.easm  # noqa: F401 - imported to resolve Project.easm_scans relationship mapper
from app.models.projects import ProjectScopeRow
from app.services.easm_scope import (
    BBOT_SEEDING_SCOPE_TYPES,
    derive_bbot_blacklist,
    derive_bbot_seeds,
)

# ---------------------------------------------------------------------------
# In-memory SQLite fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_session():
    """Provide a fresh in-memory SQLite async session for each test.

    We create only the project_scope_rows table to avoid FK resolution errors
    from other tables (events.easm_scan_id → easm_scans) that reference tables
    not needed for these unit tests.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # Build a minimal metadata containing only the tables needed for scope tests.
    # create_all on the full Base.metadata fails in SQLite because events FK resolution
    # requires easm_scans to be present (introduced in migration 010).
    scope_table = ProjectScopeRow.__table__

    async with engine.begin() as conn:
        await conn.run_sync(scope_table.create)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    await engine.dispose()


def _make_scope_row(
    project_id: uuid.UUID,
    scope_type: str,
    value: str,
    active_test_scope: bool = True,
    intel_scope: bool = True,
    exclude: bool = False,
) -> ProjectScopeRow:
    """Build a ProjectScopeRow without FK constraints (SQLite in-memory skips project FK).

    created_at is supplied explicitly because SQLite does not support the `now()`
    server_default used by the ORM - supplying it at the Python level bypasses the
    RETURNING clause that would trigger that error.
    """
    return ProjectScopeRow(
        id=uuid.uuid4(),
        project_id=project_id,
        scope_type=scope_type,
        value=value,
        active_test_scope=active_test_scope,
        intel_scope=intel_scope,
        exclude=exclude,
        created_at=datetime.now(tz=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

PROJECT_ID = uuid.uuid4()


class TestDeriveBbotSeeds:
    @pytest.mark.asyncio
    async def test_derive_seeds_includes_domain_rows(self, db_session: AsyncSession) -> None:
        """A domain row with active_test_scope=True should appear in seeds."""
        row = _make_scope_row(PROJECT_ID, "domain", "example.com")
        db_session.add(row)
        await db_session.commit()

        seeds = await derive_bbot_seeds(db_session, PROJECT_ID)
        assert "example.com" in seeds

    @pytest.mark.asyncio
    async def test_derive_seeds_includes_ip_range_rows(self, db_session: AsyncSession) -> None:
        """An ip_range row with active_test_scope=True should appear in seeds."""
        row = _make_scope_row(PROJECT_ID, "ip_range", "10.0.0.0/24")
        db_session.add(row)
        await db_session.commit()

        seeds = await derive_bbot_seeds(db_session, PROJECT_ID)
        assert "10.0.0.0/24" in seeds

    @pytest.mark.asyncio
    async def test_derive_seeds_includes_as_number_rows(self, db_session: AsyncSession) -> None:
        """An as_number row with active_test_scope=True should appear in seeds."""
        row = _make_scope_row(PROJECT_ID, "as_number", "64512")
        db_session.add(row)
        await db_session.commit()

        seeds = await derive_bbot_seeds(db_session, PROJECT_ID)
        assert "64512" in seeds

    @pytest.mark.asyncio
    async def test_derive_seeds_all_three_types(self, db_session: AsyncSession) -> None:
        """domain, ip_range, and as_number rows all produce seeds."""
        rows = [
            _make_scope_row(PROJECT_ID, "domain", "test.io"),
            _make_scope_row(PROJECT_ID, "ip_range", "192.168.0.0/16"),
            _make_scope_row(PROJECT_ID, "as_number", "65000"),
        ]
        for r in rows:
            db_session.add(r)
        await db_session.commit()

        seeds = await derive_bbot_seeds(db_session, PROJECT_ID)
        assert "test.io" in seeds
        assert "192.168.0.0/16" in seeds
        assert "65000" in seeds

    @pytest.mark.asyncio
    async def test_derive_seeds_excludes_keyword_rows(self, db_session: AsyncSession) -> None:
        """keyword rows are intel-only - must NOT appear in BBOT seeds."""
        row = _make_scope_row(PROJECT_ID, "keyword", "ransomware")
        db_session.add(row)
        await db_session.commit()

        seeds = await derive_bbot_seeds(db_session, PROJECT_ID)
        assert "ransomware" not in seeds

    @pytest.mark.asyncio
    async def test_derive_seeds_excludes_service_rows(self, db_session: AsyncSession) -> None:
        """service rows are intel-only - must NOT appear in BBOT seeds."""
        row = _make_scope_row(PROJECT_ID, "service", "http://internal.example.com:8080")
        db_session.add(row)
        await db_session.commit()

        seeds = await derive_bbot_seeds(db_session, PROJECT_ID)
        assert "http://internal.example.com:8080" not in seeds

    @pytest.mark.asyncio
    async def test_derive_seeds_excludes_certificate_rows(self, db_session: AsyncSession) -> None:
        """certificate rows are intel-only - must NOT appear in BBOT seeds."""
        row = _make_scope_row(PROJECT_ID, "certificate", "deadbeef" * 8)
        db_session.add(row)
        await db_session.commit()

        seeds = await derive_bbot_seeds(db_session, PROJECT_ID)
        assert "deadbeef" * 8 not in seeds

    @pytest.mark.asyncio
    async def test_derive_seeds_excludes_whois_rows(self, db_session: AsyncSession) -> None:
        """whois rows are intel-only - must NOT appear in BBOT seeds."""
        row = _make_scope_row(PROJECT_ID, "whois", "ACME Corp")
        db_session.add(row)
        await db_session.commit()

        seeds = await derive_bbot_seeds(db_session, PROJECT_ID)
        assert "ACME Corp" not in seeds

    @pytest.mark.asyncio
    async def test_derive_seeds_rejects_service_certificate_whois(
        self, db_session: AsyncSession
    ) -> None:
        """None of service/certificate/whois scope types should appear in seeds."""
        rows = [
            _make_scope_row(PROJECT_ID, "service", "https://svc.example.com"),
            _make_scope_row(PROJECT_ID, "certificate", "aabbccdd" * 8),
            _make_scope_row(PROJECT_ID, "whois", "ACME Corp"),
        ]
        for r in rows:
            db_session.add(r)
        await db_session.commit()

        seeds = await derive_bbot_seeds(db_session, PROJECT_ID)
        assert seeds == []

    @pytest.mark.asyncio
    async def test_derive_seeds_excludes_inactive_rows(self, db_session: AsyncSession) -> None:
        """domain row with active_test_scope=False must NOT appear in seeds."""
        row = _make_scope_row(
            PROJECT_ID, "domain", "inactive.example.com",
            active_test_scope=False, intel_scope=True,
        )
        db_session.add(row)
        await db_session.commit()

        seeds = await derive_bbot_seeds(db_session, PROJECT_ID)
        assert "inactive.example.com" not in seeds

    @pytest.mark.asyncio
    async def test_derive_seeds_excludes_intel_only_rows(self, db_session: AsyncSession) -> None:
        """active_test_scope=False, intel_scope=True - scope is intel-only; not fed to BBOT."""
        row = _make_scope_row(
            PROJECT_ID, "domain", "intel-only.example.com",
            active_test_scope=False, intel_scope=True,
        )
        db_session.add(row)
        await db_session.commit()

        seeds = await derive_bbot_seeds(db_session, PROJECT_ID)
        assert "intel-only.example.com" not in seeds

    @pytest.mark.asyncio
    async def test_derive_seeds_ignores_intel_scope_flag(self, db_session: AsyncSession) -> None:
        """intel_scope=False does NOT block seeding - active_test_scope is sole gate.

        11-CONTEXT.md §Scope consumption: 'intel_scope flag is IGNORED for BBOT -
        active_test_scope is the sole gate for scan-seeding.'
        """
        row = _make_scope_row(
            PROJECT_ID, "domain", "active-no-intel.example.com",
            active_test_scope=True, intel_scope=False,
        )
        db_session.add(row)
        await db_session.commit()

        seeds = await derive_bbot_seeds(db_session, PROJECT_ID)
        assert "active-no-intel.example.com" in seeds

    @pytest.mark.asyncio
    async def test_derive_seeds_excludes_exclude_rows(self, db_session: AsyncSession) -> None:
        """exclude=True rows must NOT appear in seeds (they go to blacklist)."""
        row = _make_scope_row(
            PROJECT_ID, "domain", "excluded.example.com",
            active_test_scope=True, exclude=True,
        )
        db_session.add(row)
        await db_session.commit()

        seeds = await derive_bbot_seeds(db_session, PROJECT_ID)
        assert "excluded.example.com" not in seeds

    @pytest.mark.asyncio
    async def test_derive_seeds_empty_scope_returns_empty_list(
        self, db_session: AsyncSession
    ) -> None:
        """No scope rows for project_id returns empty list - caller handles 422."""
        seeds = await derive_bbot_seeds(db_session, uuid.uuid4())
        assert seeds == []


class TestDeriveBbotBlacklist:
    @pytest.mark.asyncio
    async def test_derive_blacklist_includes_exclude_rows(self, db_session: AsyncSession) -> None:
        """exclude=True domain row must appear in blacklist."""
        row = _make_scope_row(
            PROJECT_ID, "domain", "excluded.example.com",
            active_test_scope=True, exclude=True,
        )
        db_session.add(row)
        await db_session.commit()

        blacklist = await derive_bbot_blacklist(db_session, PROJECT_ID)
        assert "excluded.example.com" in blacklist

    @pytest.mark.asyncio
    async def test_derive_blacklist_excludes_non_exclude_rows(
        self, db_session: AsyncSession
    ) -> None:
        """Normal (exclude=False) rows must NOT appear in blacklist."""
        row = _make_scope_row(PROJECT_ID, "domain", "normal.example.com", exclude=False)
        db_session.add(row)
        await db_session.commit()

        blacklist = await derive_bbot_blacklist(db_session, PROJECT_ID)
        assert "normal.example.com" not in blacklist

    @pytest.mark.asyncio
    async def test_derive_blacklist_empty_if_no_excludes(self, db_session: AsyncSession) -> None:
        """No exclude rows → empty blacklist list."""
        row = _make_scope_row(PROJECT_ID, "domain", "no-exclude.example.com", exclude=False)
        db_session.add(row)
        await db_session.commit()

        blacklist = await derive_bbot_blacklist(db_session, PROJECT_ID)
        assert blacklist == []

    @pytest.mark.asyncio
    async def test_derive_blacklist_ip_range_exclude(self, db_session: AsyncSession) -> None:
        """ip_range exclude rows go to blacklist."""
        row = _make_scope_row(
            PROJECT_ID, "ip_range", "10.0.0.0/8",
            active_test_scope=True, exclude=True,
        )
        db_session.add(row)
        await db_session.commit()

        blacklist = await derive_bbot_blacklist(db_session, PROJECT_ID)
        assert "10.0.0.0/8" in blacklist


class TestBbotSeedingTypes:
    def test_seeding_types_frozenset(self) -> None:
        """BBOT_SEEDING_SCOPE_TYPES must be a frozenset."""
        assert isinstance(BBOT_SEEDING_SCOPE_TYPES, frozenset)

    def test_seeding_types_contains_expected_values(self) -> None:
        assert BBOT_SEEDING_SCOPE_TYPES == frozenset({"domain", "ip_range", "as_number"})

    def test_intel_only_types_not_in_seeding_set(self) -> None:
        """keyword, service, certificate, whois must NOT be in BBOT_SEEDING_SCOPE_TYPES."""
        intel_only = {"keyword", "service", "certificate", "whois"}
        overlap = intel_only & BBOT_SEEDING_SCOPE_TYPES
        assert not overlap, f"Intel-only types found in seeding set: {overlap}"
