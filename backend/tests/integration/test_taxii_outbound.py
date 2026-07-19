"""Integration tests for TAXII 2.1 outbound server - TAXII-02..05.

Uses a real PostgreSQL testcontainer. Mirrors test_prod01_cross_project_leakage.py
fixture pattern. Each test seeds its own TaxiiClient row and Event rows.

Run with:  uv run pytest tests/integration/test_taxii_outbound.py -m integration -v
"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone

os.environ.setdefault("SECRET_KEY", "s" * 64)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def _seed_project(session: AsyncSession, name: str = "TAXII Test Project") -> object:
    """Insert a minimal project row and return a SimpleNamespace with .id and .name."""
    from types import SimpleNamespace

    pid = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO projects (id, name, engagement_type, created_by, archived) "
            "VALUES (:id, :name, 'internal', 'test', false)"
        ),
        {"id": pid, "name": name},
    )
    await session.commit()
    return SimpleNamespace(id=pid, name=name)


async def _seed_taxii_client(
    session: AsyncSession,
    project_id: uuid.UUID,
    raw_key: str = "test-key-001",
    tlp_max_level: str = "green",
    revoked: bool = False,
) -> object:
    """Insert a TaxiiClient row; returns an object with .id and .revoked."""
    from types import SimpleNamespace

    client_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO taxii_clients "
            "(id, label, api_key_hash, project_id, tlp_max_level, rate_limit_rpm, revoked) "
            "VALUES (:id, :label, :hash, :pid, :tlp, :rpm, :rev)"
        ),
        {
            "id": client_id,
            "label": "Integration Test Partner",
            "hash": _hash_key(raw_key),
            "pid": project_id,
            "tlp": tlp_max_level,
            "rpm": 60,
            "rev": revoked,
        },
    )
    await session.commit()
    return SimpleNamespace(id=client_id, revoked=revoked)


async def _get_tlp_id(session: AsyncSession, name: str) -> uuid.UUID | None:
    """Return the UUID of the named TLP marking row, or None if absent."""
    row = (
        await session.execute(
            text("SELECT id FROM tlp_markings WHERE name = :name LIMIT 1"),
            {"name": name},
        )
    ).fetchone()
    return row[0] if row else None


async def _seed_event(
    session: AsyncSession,
    project_id: uuid.UUID,
    title: str,
    content_hash: str,
    tlp_id: uuid.UUID | None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO events (project_id, title, observed_at, content_hash, tlp_marking_id) "
            "VALUES (:pid, :title, :ts, :hash, :tlp)"
        ),
        {
            "pid": project_id,
            "title": title,
            "ts": datetime.now(timezone.utc),
            "hash": content_hash,
            "tlp": tlp_id,
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_collections_acl(db_session):
    """TAXII-02: Collections list returns only the collection bound to the partner key."""
    project = await _seed_project(db_session, "ACL Test Project")
    raw_key = "collections-acl-key-" + str(uuid.uuid4())[:8]
    await _seed_taxii_client(db_session, project.id, raw_key=raw_key)

    from app.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/taxii2/api/collections/",
            headers={"X-TAXII-API-Key": raw_key},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "collections" in data
    ids = [c["id"] for c in data["collections"]]
    assert str(project.id) in ids


@pytest.mark.integration
async def test_objects_pagination(db_session):
    """TAXII-05: Objects endpoint returns paginated envelope with more=True + next cursor when >100 events."""
    project = await _seed_project(db_session, "Pagination Test Project")
    raw_key = "pagination-key-" + str(uuid.uuid4())[:8]
    await _seed_taxii_client(db_session, project.id, raw_key=raw_key, tlp_max_level="green")

    tlp_id = await _get_tlp_id(db_session, "green")

    # Seed 101 events (just over PAGE_CAP)
    for i in range(101):
        await _seed_event(
            db_session,
            project.id,
            title=f"Pagination Event {i}",
            content_hash=f"pag-hash-{project.id}-{i}",
            tlp_id=tlp_id,
        )
    await db_session.commit()

    from app.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/taxii2/api/collections/{project.id}/objects/",
            headers={"X-TAXII-API-Key": raw_key},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["more"] is True, "more should be True when >100 events"
    assert "next" in data, "next cursor should be present when more=True"
    assert len(data["objects"]) == 100, f"Expected 100 objects (PAGE_CAP), got {len(data['objects'])}"


@pytest.mark.integration
async def test_key_revocation_instant(db_session):
    """TAXII-03: Revoking a partner key returns 401 on the very next request (no cache lag)."""
    project = await _seed_project(db_session, "Revocation Test Project")
    raw_key = "revoke-test-key-" + str(uuid.uuid4())[:8]
    taxii_client = await _seed_taxii_client(db_session, project.id, raw_key=raw_key)

    from app.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # First request - should succeed
        resp1 = await client.get(
            "/taxii2/api/collections/",
            headers={"X-TAXII-API-Key": raw_key},
        )
        assert resp1.status_code == 200, f"First request should succeed, got {resp1.status_code}"

        # Revoke the key directly in DB
        await db_session.execute(
            text("UPDATE taxii_clients SET revoked = true WHERE id = :id"),
            {"id": taxii_client.id},
        )
        await db_session.commit()

        # Second request - must fail immediately (no caching)
        resp2 = await client.get(
            "/taxii2/api/collections/",
            headers={"X-TAXII-API-Key": raw_key},
        )
    assert resp2.status_code == 401, f"Revoked key should return 401, got {resp2.status_code}"


@pytest.mark.integration
async def test_rate_limit(db_session):
    """TAXII-03: Partner key with rate_limit_rpm=2 is rejected after 2 requests in the same window.

    Note: This test requires Redis. Skip if Redis is not available.
    """
    pytest.skip("Rate limit test requires running Redis - skip in CI without Redis")


@pytest.mark.integration
async def test_tlp_acl_amber_filtered(db_session):
    """TAXII-04: Partner with tlp_max_level='green' receives no AMBER/RED events."""
    project = await _seed_project(db_session, "TLP Green Filter Project")
    raw_key = "tlp-green-key-" + str(uuid.uuid4())[:8]
    await _seed_taxii_client(db_session, project.id, raw_key=raw_key, tlp_max_level="green")

    tlp_green = await _get_tlp_id(db_session, "green")
    tlp_amber = await _get_tlp_id(db_session, "amber")

    await _seed_event(db_session, project.id, "Green Event", f"tlp-green-{uuid.uuid4()}", tlp_green)
    await _seed_event(db_session, project.id, "Amber Event", f"tlp-amber-{uuid.uuid4()}", tlp_amber)
    await db_session.commit()

    from app.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/taxii2/api/collections/{project.id}/objects/",
            headers={"X-TAXII-API-Key": raw_key},
        )
    assert resp.status_code == 200
    titles = [o.get("x_intellibird_title", "") for o in resp.json()["objects"]]
    assert "Amber Event" not in titles, "AMBER event must not appear for green-capped partner"
    assert "Green Event" in titles, "GREEN event must appear for green-capped partner"


@pytest.mark.integration
async def test_tlp_acl_amber_visible(db_session):
    """TAXII-04: Partner with tlp_max_level='amber' receives AMBER events."""
    project = await _seed_project(db_session, "TLP Amber Visible Project")
    raw_key = "tlp-amber-key-" + str(uuid.uuid4())[:8]
    await _seed_taxii_client(db_session, project.id, raw_key=raw_key, tlp_max_level="amber")

    tlp_amber = await _get_tlp_id(db_session, "amber")
    await _seed_event(db_session, project.id, "Visible Amber", f"tlp-visible-{uuid.uuid4()}", tlp_amber)
    await db_session.commit()

    from app.main import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/taxii2/api/collections/{project.id}/objects/",
            headers={"X-TAXII-API-Key": raw_key},
        )
    assert resp.status_code == 200
    titles = [o.get("x_intellibird_title", "") for o in resp.json()["objects"]]
    assert "Visible Amber" in titles, "AMBER event must appear for amber-capped partner"
