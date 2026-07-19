"""IOC-01 uniqueness integration tests.

Gates the `UNIQUE (project_id, type, normalized_value) NULLS NOT DISTINCT`
index on the iocs table introduced by migration 023.

Uses the PINNED `db_session` fixture from
backend/tests/integration/conftest.py per IntelliBird MEMORY.md
`project_test_pollution`.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


@pytest.fixture(autouse=True)
async def _truncate_iocs(db_session):
    """Per-test isolation for the iocs table. The shared `db_session` fixture
    in tests/integration/conftest.py does NOT truncate iocs (added in this
    plan), so tests must clear it themselves to avoid cross-test pollution
    (see IntelliBird MEMORY.md `project_test_pollution`).
    """
    await db_session.execute(text("TRUNCATE TABLE ioc_event_links, iocs RESTART IDENTITY CASCADE"))
    await db_session.commit()
    yield


@pytest.mark.asyncio
async def test_unique_nulls_not_distinct_rejects_double_global(db_session):
    """Two global rows (project_id NULL) with same (type, normalized_value)
    must be rejected by the NULLS NOT DISTINCT unique index.
    """
    await db_session.execute(
        text(
            "INSERT INTO iocs (project_id, type, value, normalized_value, ttl_days) "
            "VALUES (NULL, 'ip', '1.2.3.4', '1.2.3.4', 30)"
        )
    )
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO iocs (project_id, type, value, normalized_value, ttl_days) "
                "VALUES (NULL, 'ip', '1.2.3.4', '1.2.3.4', 30)"
            )
        )
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_unique_allows_distinct_types_in_global_scope(db_session):
    """Two global rows with same normalized_value but different `type`
    are independent entries - must be permitted.
    """
    await db_session.execute(
        text(
            "INSERT INTO iocs (project_id, type, value, normalized_value, ttl_days) "
            "VALUES (NULL, 'ip', '1.2.3.4', '1.2.3.4', 30)"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO iocs (project_id, type, value, normalized_value, ttl_days) "
            "VALUES (NULL, 'domain', '1.2.3.4', '1.2.3.4', 180)"
        )
    )
    await db_session.commit()

    result = await db_session.execute(
        text(
            "SELECT COUNT(*) FROM iocs "
            "WHERE project_id IS NULL AND normalized_value = '1.2.3.4'"
        )
    )
    assert result.scalar() == 2
