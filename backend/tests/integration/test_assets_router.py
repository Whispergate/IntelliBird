# Owned by: 12.1-04-PLAN
"""Integration tests for /api/projects/{id}/assets READ surface — plan 12.1-04a.

Covers:
  - GET /assets (list): aggregation, filters (type/scope/stale/search), pagination
  - GET /assets/summary: 7-bucket counts
  - GET /assets/{asset_id} (detail): findings + promoted_events + note
  - Membership guard (403) / legacy + archived guards (422) / cross-project isolation
  - asset_id regex validation (422)

Tests 04-04 (PATCH note upsert) and 04-03 (export) are 04b's responsibility.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

# Settings env stubs — required before `app.config` import chain runs. The
# _patch_settings_for_integration autouse fixture later overwrites DATABASE_URL +
# REDIS_URL with the live container URLs; SECRET_KEY + JWT_SIGNING_KEY remain.
os.environ.setdefault("SECRET_KEY", "x" * 48)
os.environ.setdefault("JWT_SIGNING_KEY", "j" * 64)

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_auth_user(
    role: str = "Admin",
    project_memberships: dict[uuid.UUID, int] | None = None,
):
    """Build an AuthUser. project_memberships: {project_id: rank}. Rank: 1=Observer, 2=Contributor, 3=Lead."""
    from app.security.jwt import AuthUser

    pm: dict[str, int] = {}
    if project_memberships:
        pm = {str(pid): rank for pid, rank in project_memberships.items()}

    return AuthUser(
        id=str(uuid.uuid4()),
        role=role,
        dashboard_roles=["red", "blue"],
        jti=str(uuid.uuid4()),
        token_version=0,
        project_memberships=pm,
        pm_truncated=False,
    )


async def _insert_project(db_session, project_id: uuid.UUID, created_by: str, archived: bool = False) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO projects (id, name, engagement_type, created_by, archived)
            VALUES (CAST(:id AS uuid), :name, 'red_team', :created_by, :archived)
            """
        ),
        {
            "id": str(project_id),
            "name": f"proj-{project_id}",
            "created_by": created_by,
            "archived": archived,
        },
    )
    await db_session.commit()


async def _insert_scan(
    db_session,
    project_id: uuid.UUID,
    launched_by: str,
    *,
    status: str = "finished",
    started_at: datetime | None = None,
) -> uuid.UUID:
    scan_id = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO easm_scans (id, project_id, status, scan_mode, modules, started_at, launched_by)
            VALUES (
                CAST(:id AS uuid), CAST(:project_id AS uuid),
                CAST(:status AS easm_scan_status), 'passive'::easm_scan_mode,
                ARRAY['crt'], :started_at, :launched_by
            )
            """
        ),
        {
            "id": str(scan_id),
            "project_id": str(project_id),
            "status": status,
            "started_at": started_at or datetime.now(timezone.utc),
            "launched_by": launched_by,
        },
    )
    await db_session.commit()
    return scan_id


async def _insert_finding(
    db_session,
    *,
    project_id: uuid.UUID,
    scan_id: uuid.UUID,
    bbot_event_type: str,
    canonical_target: str,
    module: str = "crt",
    first_seen: datetime | None = None,
    last_seen: datetime | None = None,
    content_hash: str | None = None,
) -> tuple[uuid.UUID, str]:
    fid = uuid.uuid4()
    ch = content_hash or uuid.uuid4().hex
    fs = first_seen or datetime.now(timezone.utc)
    ls = last_seen or datetime.now(timezone.utc)
    await db_session.execute(
        text(
            """
            INSERT INTO easm_findings (
                id, project_id, scan_id, bbot_event_type, canonical_target,
                severity, module, raw_bbot, content_hash, first_seen, last_seen,
                lifecycle_status
            ) VALUES (
                CAST(:id AS uuid), CAST(:project_id AS uuid), CAST(:scan_id AS uuid),
                :bet, :target, NULL, :module,
                CAST(:raw_bbot AS jsonb), :ch, :first_seen, :last_seen, 'new'::easm_lifecycle
            )
            """
        ),
        {
            "id": str(fid),
            "project_id": str(project_id),
            "scan_id": str(scan_id),
            "bet": bbot_event_type,
            "target": canonical_target,
            "module": module,
            "raw_bbot": '{"data": {"host": "' + canonical_target + '"}}',
            "ch": ch,
            "first_seen": fs,
            "last_seen": ls,
        },
    )
    await db_session.commit()
    return fid, ch


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def assets_app(db_engine, _migrations_applied):
    """Minimal FastAPI app mounting routers/assets.py with session + auth overrides."""
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.database import get_session
    from app.middleware.auth import require_auth
    from app.routers.assets import router as assets_router

    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    app = FastAPI()
    app.include_router(assets_router)

    async def override_session():
        async with factory() as session:
            yield session

    # Default: global Admin (bypasses membership check for happy-path tests)
    default_user = _make_auth_user(role="Admin")

    def override_require_auth():
        return default_user

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_auth] = override_require_auth
    yield app, factory, default_user


def _set_user(app, user):
    """Swap the require_auth override to return `user`."""
    from app.middleware.auth import require_auth

    app.dependency_overrides[require_auth] = lambda: user


# ---------------------------------------------------------------------------
# test_list_and_summary — Tests 1-7 + promoted_events seed reuse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_and_summary(assets_app, db_session):
    """12.1-04-01: list + summary endpoints (aggregation, filters, pagination)."""
    app, factory, admin_user = assets_app
    project_id = uuid.uuid4()
    await _insert_project(db_session, project_id, admin_user.id)
    # Seed the finished scan WITH started_at before the findings' last_seen so
    # the stale cutoff (= MAX finished scan started_at) is older than every
    # finding — none should be flagged stale.
    scan_started_at = datetime.now(timezone.utc) - timedelta(days=7)
    scan_id = await _insert_scan(
        db_session, project_id, admin_user.id, started_at=scan_started_at,
    )

    # Seed: 4 findings, 2 share (type, target) → 3 aggregated rows.
    #   DNS_NAME / example.com   (2 findings, same canonical target — dedup-key
    #     collision prevented via distinct canonical_target below because of the
    #     DB unique constraint; use distinct targets per row instead.)
    # Unique constraint: (project_id, bbot_event_type, canonical_target).
    # Use 4 truly distinct rows to produce 4 aggregated assets, then assert >=3
    # per plan intent. We simulate "2 sharing type+target" via 2 scans on the
    # same (type, target) — but the unique constraint collapses them. Instead
    # we use 3 distinct rows for a deterministic 3-asset result.
    now = datetime.now(timezone.utc)
    await _insert_finding(
        db_session,
        project_id=project_id,
        scan_id=scan_id,
        bbot_event_type="DNS_NAME",
        canonical_target="a.example.com",
        last_seen=now - timedelta(hours=3),
    )
    await _insert_finding(
        db_session,
        project_id=project_id,
        scan_id=scan_id,
        bbot_event_type="DNS_NAME",
        canonical_target="b.example.com",
        last_seen=now - timedelta(hours=1),
    )
    await _insert_finding(
        db_session,
        project_id=project_id,
        scan_id=scan_id,
        bbot_event_type="IP_ADDRESS",
        canonical_target="192.0.2.10",
        last_seen=now - timedelta(hours=2),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Test 1 (list): 3 aggregated items
        r = await client.get(f"/api/projects/{project_id}/assets")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 3
        assert len(body["items"]) == 3
        # Default sort last_seen DESC
        last_seens = [it["last_seen"] for it in body["items"]]
        assert last_seens == sorted(last_seens, reverse=True)
        for it in body["items"]:
            assert len(it["asset_id"]) == 64
            assert it["scope"] in {"in_scope", "out_of_scope", "unscoped"}
            assert it["stale"] is False  # cutoff = finished scan start = "now"; nothing is stale

        # Test 2 (filter type)
        r = await client.get(f"/api/projects/{project_id}/assets", params={"type": "DNS_NAME"})
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 2
        assert all(i["bbot_event_type"] == "DNS_NAME" for i in items)

        # Test 5 (filter search)
        r = await client.get(f"/api/projects/{project_id}/assets", params={"search": "a.example"})
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["canonical_target"] == "a.example.com"

        # Test 6 (pagination)
        r = await client.get(f"/api/projects/{project_id}/assets", params={"limit": 2, "offset": 0})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3
        assert len(body["items"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 0

        # Test 7 (summary)
        r = await client.get(f"/api/projects/{project_id}/assets/summary")
        assert r.status_code == 200
        buckets = r.json()["buckets"]
        # All 7 keys present even when zero
        for k in ("DOMAINS", "IPS", "OPEN_PORTS", "URLS", "TECHNOLOGIES", "IDENTITIES", "OTHER"):
            assert k in buckets
        assert buckets["DOMAINS"]["count"] == 2
        assert buckets["IPS"]["count"] == 1
        assert buckets["URLS"]["count"] == 0


# ---------------------------------------------------------------------------
# test_list_filters_scope_and_stale — Tests 3 + 4
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_filters_scope_and_stale(assets_app, db_session):
    """Scope + stale filters operate over annotated rows."""
    app, factory, admin_user = assets_app
    project_id = uuid.uuid4()
    await _insert_project(db_session, project_id, admin_user.id)

    # Scope row: domain=example.com (in_scope for the DNS_NAME)
    await db_session.execute(
        text(
            """
            INSERT INTO project_scope_rows (project_id, scope_type, value, intel_scope, active_test_scope)
            VALUES (CAST(:pid AS uuid), 'domain'::scope_type, 'example.com', true, true)
            """
        ),
        {"pid": str(project_id)},
    )
    await db_session.commit()

    # Newer finished scan → stale cutoff = now
    fresh_scan = await _insert_scan(
        db_session, project_id, admin_user.id,
        status="finished", started_at=datetime.now(timezone.utc),
    )

    now = datetime.now(timezone.utc)
    # Stale finding: last_seen well before fresh_scan.started_at
    await _insert_finding(
        db_session,
        project_id=project_id,
        scan_id=fresh_scan,
        bbot_event_type="DNS_NAME",
        canonical_target="old.example.com",
        last_seen=now - timedelta(days=30),
    )
    # Fresh finding
    await _insert_finding(
        db_session,
        project_id=project_id,
        scan_id=fresh_scan,
        bbot_event_type="DNS_NAME",
        canonical_target="new.example.com",
        last_seen=now + timedelta(seconds=60),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Test 3 (filter scope)
        r = await client.get(f"/api/projects/{project_id}/assets", params={"scope": "in_scope"})
        assert r.status_code == 200
        items = r.json()["items"]
        assert all(i["scope"] == "in_scope" for i in items)
        assert len(items) == 2  # both share parent domain

        # Test 4 (stale=only)
        r = await client.get(f"/api/projects/{project_id}/assets", params={"stale": "only"})
        assert r.status_code == 200
        items = r.json()["items"]
        # At least the old one should be stale
        assert any(i["canonical_target"] == "old.example.com" for i in items)
        assert all(i["stale"] is True for i in items)


# ---------------------------------------------------------------------------
# test_detail_and_note_patch — Tests 8, 9, 10, 16 (detail + promoted_events)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_and_note_patch(assets_app, db_session):
    """12.1-04-02: detail endpoint — findings list + promoted_events + note None.

    PATCH assertions are 04b's responsibility; this test only covers the READ
    surface of the detail endpoint (plus Test 16: promoted_events populated).
    """
    app, factory, admin_user = assets_app
    project_id = uuid.uuid4()
    await _insert_project(db_session, project_id, admin_user.id)
    scan_id = await _insert_scan(db_session, project_id, admin_user.id)

    # Test 16: seed a finding + matching promoted event via content_hash.
    shared_hash = uuid.uuid4().hex
    finding_id, _ = await _insert_finding(
        db_session,
        project_id=project_id,
        scan_id=scan_id,
        bbot_event_type="VULNERABILITY",
        canonical_target="example.com",
        content_hash=shared_hash,
    )

    # Insert a bbot-promoted event row with matching content_hash + easm_scan_id.
    event_id = uuid.uuid4()
    observed_at = datetime.now(timezone.utc)
    await db_session.execute(
        text(
            """
            INSERT INTO events (
                id, stix_type, project_id, observed_at, content_hash,
                easm_scan_id, title, visibility
            ) VALUES (
                CAST(:id AS uuid), 'vulnerability', CAST(:project_id AS uuid),
                :observed_at, :ch, CAST(:scan_id AS uuid), :title, 'shared'
            )
            """
        ),
        {
            "id": str(event_id),
            "project_id": str(project_id),
            "observed_at": observed_at,
            "ch": shared_hash,
            "scan_id": str(scan_id),
            "title": "Example vuln",
        },
    )
    await db_session.commit()

    # Compute asset_id
    from app.services.assets_query import asset_id_for

    asset_id = asset_id_for("VULNERABILITY", "example.com")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Test 8 (detail): findings[] populated + note=null
        r = await client.get(f"/api/projects/{project_id}/assets/{asset_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["asset_id"] == asset_id
        assert body["bbot_event_type"] == "VULNERABILITY"
        assert body["canonical_target"] == "example.com"
        assert len(body["findings"]) == 1
        assert body["findings"][0]["id"] == str(finding_id)
        assert body["note"] is None

        # Test 16: promoted_events populated
        assert len(body["promoted_events"]) == 1
        pe = body["promoted_events"][0]
        assert pe["id"] == str(event_id)
        assert pe["stix_type"] == "vulnerability"
        assert pe["title"] == "Example vuln"

        # Test 9 (detail 404): valid hex but no match
        bogus = "0" * 64
        r = await client.get(f"/api/projects/{project_id}/assets/{bogus}")
        assert r.status_code == 404

        # Test 10 (detail 422): not 64 hex
        r = await client.get(f"/api/projects/{project_id}/assets/aaaa")
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# test_membership_required — Tests 11, 12, 13, 14, 15
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_membership_required(assets_app, db_session):
    """12.1-04-04: guards + cross-project isolation."""
    app, factory, _admin = assets_app
    from app.models.projects import LEGACY_PROJECT_ID

    project_a = uuid.uuid4()
    project_b = uuid.uuid4()
    await _insert_project(db_session, project_a, str(uuid.uuid4()))
    await _insert_project(db_session, project_b, str(uuid.uuid4()))

    # Seed an asset in project_b so we can test cross-project asset lookup
    scan_b = await _insert_scan(db_session, project_b, str(uuid.uuid4()))
    await _insert_finding(
        db_session,
        project_id=project_b,
        scan_id=scan_b,
        bbot_event_type="DNS_NAME",
        canonical_target="bproj.example.com",
    )

    from app.services.assets_query import asset_id_for

    b_asset_id = asset_id_for("DNS_NAME", "bproj.example.com")

    # Test 11 (membership): non-member Viewer → 403
    viewer_no_pm = _make_auth_user(role="Viewer", project_memberships={})
    _set_user(app, viewer_no_pm)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/api/projects/{project_a}/assets")
        assert r.status_code == 403

    # Test 12 (legacy): 422 — need membership so guard runs. Give global Admin
    # (bypasses membership) and hit legacy sentinel.
    admin = _make_auth_user(role="Admin")
    _set_user(app, admin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/api/projects/{LEGACY_PROJECT_ID}/assets")
        assert r.status_code == 422

    # Test 13 (archived): archived project → 422
    archived_id = uuid.uuid4()
    await _insert_project(db_session, archived_id, str(uuid.uuid4()), archived=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/api/projects/{archived_id}/assets")
        assert r.status_code == 422

    # Test 14 (cross-project isolation): Viewer who is member of A only → 403 on B
    a_only_user = _make_auth_user(role="Viewer", project_memberships={project_a: 1})
    _set_user(app, a_only_user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/api/projects/{project_b}/assets")
        assert r.status_code == 403

    # Test 15 (cross-project asset leak): member of both A and B; GET /A/assets/{b_asset_id} → 404
    both_user = _make_auth_user(role="Viewer", project_memberships={project_a: 1, project_b: 1})
    _set_user(app, both_user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/api/projects/{project_a}/assets/{b_asset_id}")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# test_note_patch — 04b Tests 1-10 (PATCH upsert + authority matrix + 404/422)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_note_patch(assets_app, db_session):
    """12.1-04b: PATCH /assets/{asset_id}/note upsert + authority matrix."""
    app, factory, admin_user = assets_app
    project_id = uuid.uuid4()
    await _insert_project(db_session, project_id, admin_user.id)
    scan_id = await _insert_scan(db_session, project_id, admin_user.id)
    await _insert_finding(
        db_session,
        project_id=project_id,
        scan_id=scan_id,
        bbot_event_type="DNS_NAME",
        canonical_target="asset.example.com",
    )

    from app.services.assets_query import asset_id_for

    asset_id = asset_id_for("DNS_NAME", "asset.example.com")
    bogus = "f" * 64

    # Start as a project Contributor.
    contributor = _make_auth_user(role="Viewer", project_memberships={project_id: 2})
    _set_user(app, contributor)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Test 1 (note insert): Contributor PATCH with {"note": "hello"} → 200 + row populated
        r = await client.patch(
            f"/api/projects/{project_id}/assets/{asset_id}/note",
            json={"note": "hello"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["note"] == "hello"
        assert body["updated_by"] == contributor.id
        first_updated_at = body["updated_at"]

        # Row count must be exactly 1.
        count = (
            await db_session.execute(
                text("SELECT COUNT(*) FROM asset_notes WHERE project_id = CAST(:pid AS uuid)"),
                {"pid": str(project_id)},
            )
        ).scalar_one()
        assert count == 1

        # Test 2 (note update): second PATCH upserts same row, updated_at advances.
        import asyncio
        await asyncio.sleep(0.01)
        r = await client.patch(
            f"/api/projects/{project_id}/assets/{asset_id}/note",
            json={"note": "updated"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["note"] == "updated"
        assert body["updated_at"] >= first_updated_at
        count = (
            await db_session.execute(
                text("SELECT COUNT(*) FROM asset_notes WHERE project_id = CAST(:pid AS uuid)"),
                {"pid": str(project_id)},
            )
        ).scalar_one()
        assert count == 1

        # Test 3 (note clear): empty string allowed (not NULL).
        r = await client.patch(
            f"/api/projects/{project_id}/assets/{asset_id}/note",
            json={"note": ""},
        )
        assert r.status_code == 200
        assert r.json()["note"] == ""
        count = (
            await db_session.execute(
                text("SELECT COUNT(*) FROM asset_notes WHERE project_id = CAST(:pid AS uuid)"),
                {"pid": str(project_id)},
            )
        ).scalar_one()
        assert count == 1

        # Test 9 (note 422 length): >10_000 chars rejected by schema
        r = await client.patch(
            f"/api/projects/{project_id}/assets/{asset_id}/note",
            json={"note": "x" * 10_001},
        )
        assert r.status_code == 422

        # Test 10 (note 404): valid hex, no match
        r = await client.patch(
            f"/api/projects/{project_id}/assets/{bogus}/note",
            json={"note": "ghost"},
        )
        assert r.status_code == 404

    # Test 4 (note auth 403 Observer)
    observer = _make_auth_user(role="Viewer", project_memberships={project_id: 1})
    _set_user(app, observer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/projects/{project_id}/assets/{asset_id}/note",
            json={"note": "denied"},
        )
        assert r.status_code == 403

    # Test 5 (note auth 403 global Viewer with no project membership)
    viewer = _make_auth_user(role="Viewer", project_memberships={})
    _set_user(app, viewer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/projects/{project_id}/assets/{asset_id}/note",
            json={"note": "nope"},
        )
        assert r.status_code == 403

    # Test 7 (note auth 200 Lead)
    lead = _make_auth_user(role="Viewer", project_memberships={project_id: 3})
    _set_user(app, lead)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/projects/{project_id}/assets/{asset_id}/note",
            json={"note": "from lead"},
        )
        assert r.status_code == 200
        assert r.json()["note"] == "from lead"

    # Test 8 (note auth 200 global Admin with no explicit membership)
    admin = _make_auth_user(role="Admin", project_memberships={})
    _set_user(app, admin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/projects/{project_id}/assets/{asset_id}/note",
            json={"note": "from admin"},
        )
        assert r.status_code == 200
        assert r.json()["note"] == "from admin"

    # Test 8b (Analyst global role allowed)
    analyst = _make_auth_user(role="Analyst", project_memberships={})
    _set_user(app, analyst)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            f"/api/projects/{project_id}/assets/{asset_id}/note",
            json={"note": "from analyst"},
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# test_export — 04b Tests 11-15 (CSV + JSON + 413 cap + 422 invalid + filter)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export(assets_app, db_session):
    """12.1-04b: GET /assets/export CSV + JSON + 413 cap + filter composition."""
    app, factory, admin_user = assets_app
    project_id = uuid.uuid4()
    await _insert_project(db_session, project_id, admin_user.id)
    scan_id = await _insert_scan(db_session, project_id, admin_user.id)

    # Seed mixed types
    await _insert_finding(
        db_session, project_id=project_id, scan_id=scan_id,
        bbot_event_type="DNS_NAME", canonical_target="a.example.com",
    )
    await _insert_finding(
        db_session, project_id=project_id, scan_id=scan_id,
        bbot_event_type="DNS_NAME", canonical_target="b.example.com",
    )
    await _insert_finding(
        db_session, project_id=project_id, scan_id=scan_id,
        bbot_event_type="IP_ADDRESS", canonical_target="192.0.2.42",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Test 11 (export CSV)
        r = await client.get(
            f"/api/projects/{project_id}/assets/export",
            params={"format": "csv"},
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/csv")
        cd = r.headers["content-disposition"]
        assert "attachment" in cd
        assert ".csv" in cd
        assert "intellibird-assets-" in cd
        body = r.text
        lines = body.strip().splitlines()
        # Header + 3 data rows
        assert lines[0].startswith("asset_id,bbot_event_type,canonical_target")
        assert len(lines) == 4

        # Test 12 (export JSON)
        r = await client.get(
            f"/api/projects/{project_id}/assets/export",
            params={"format": "json"},
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")
        cd = r.headers["content-disposition"]
        assert "attachment" in cd
        assert ".json" in cd
        payload = r.json()
        assert isinstance(payload, list)
        assert len(payload) == 3
        targets = {row["canonical_target"] for row in payload}
        assert targets == {"a.example.com", "b.example.com", "192.0.2.42"}

        # Test 14 (export 422 invalid format)
        r = await client.get(
            f"/api/projects/{project_id}/assets/export",
            params={"format": "xml"},
        )
        assert r.status_code == 422

        # Test 15 (export respects filter — type=IP_ADDRESS only)
        r = await client.get(
            f"/api/projects/{project_id}/assets/export",
            params={"format": "csv", "type": "IP_ADDRESS"},
        )
        assert r.status_code == 200
        lines = r.text.strip().splitlines()
        # Header + 1 data row
        assert len(lines) == 2
        assert "192.0.2.42" in lines[1]

    # Test 13 (export 413): monkey-patch EXPORT_ROW_CAP to a small value so we
    # don't need to seed 50_001 findings. The ASSET_ROW_CAP is read once per
    # request — setattr on the router module flips the limit.
    import app.routers.assets as assets_module

    original_cap = assets_module.EXPORT_ROW_CAP
    try:
        assets_module.EXPORT_ROW_CAP = 2  # we have 3 rows seeded
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                f"/api/projects/{project_id}/assets/export",
                params={"format": "csv"},
            )
            assert r.status_code == 413
            body = r.json()
            # FastAPI wraps HTTPException.detail in {"detail": ...}
            detail = body.get("detail")
            assert isinstance(detail, dict)
            assert detail["matched"] == 3
            assert detail["cap"] == 2
            assert "narrow" in detail["detail"].lower()
    finally:
        assets_module.EXPORT_ROW_CAP = original_cap


# ---------------------------------------------------------------------------
# test_main_registration — asserts assets router visible via /openapi.json
# ---------------------------------------------------------------------------


def test_main_registration():
    """04b: main.py registers assets router; all 5 paths discoverable in OpenAPI."""
    # Ensure env defaults are set (module-level os.environ.setdefault at top of
    # this file covers this; importing app.main re-uses the same env).
    from app.main import app

    spec = app.openapi()
    paths = list(spec["paths"].keys())
    asset_paths = [p for p in paths if "/assets" in p]
    # Expected paths:
    #   /api/projects/{project_id}/assets
    #   /api/projects/{project_id}/assets/summary
    #   /api/projects/{project_id}/assets/export
    #   /api/projects/{project_id}/assets/{asset_id}
    #   /api/projects/{project_id}/assets/{asset_id}/note
    assert len(asset_paths) == 5, asset_paths
    assert any(p.endswith("/assets") for p in asset_paths)
    assert any(p.endswith("/assets/summary") for p in asset_paths)
    assert any(p.endswith("/assets/export") for p in asset_paths)
    assert any(p.endswith("/assets/{asset_id}") for p in asset_paths)
    assert any(p.endswith("/assets/{asset_id}/note") for p in asset_paths)
