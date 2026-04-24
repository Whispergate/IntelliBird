"""Integration test for BRP-05 webhook-reuse guarantee + events filter toggle (12-06).

Two contracts:

1. /api/events?include_brand_match={bool} — default false excludes events
   tagged 'brand-match'; true includes them. Filter discrimination is by tag,
   mirroring how brand_synth.build_event_dict canonically tags events.
2. Zero-new-webhook-code guarantee (BRP-05): no files under
   backend/app/services/webhook_payloads/ mention 'brand'. Existing
   webhook_dispatcher composes webhook payloads from event tags/description —
   brand events flow through the same code path as any other tagged event.
"""
from __future__ import annotations

import pathlib
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.integration


def _make_auth_user(role: str = "Admin", project_id: uuid.UUID | None = None, project_rank: int = 3):
    from app.security.jwt import AuthUser

    pm: dict[str, int] = {}
    if project_id is not None:
        pm[str(project_id)] = project_rank

    return AuthUser(
        id=str(uuid.uuid4()),
        role=role,
        dashboard_roles=["red", "blue"],
        jti=str(uuid.uuid4()),
        token_version=0,
        project_memberships=pm,
        pm_truncated=False,
    )


@pytest_asyncio.fixture
async def events_app(db_engine, _migrations_applied):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from fastapi import FastAPI

    from app.database import get_session
    from app.middleware.auth import require_auth
    # Ensure all ORM models are imported so SQLAlchemy class registry resolves
    # Event.easm_scan_id FK → EASMScan.
    import app.models.easm  # noqa: F401
    from app.routers.events import router as events_router

    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)

    app = FastAPI()
    app.include_router(events_router, prefix="/api")

    async def override_session():
        async with factory() as session:
            yield session

    admin_user = _make_auth_user(role="Admin")
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_auth] = lambda: admin_user
    yield app, factory, admin_user


async def _seed_project_and_events(
    db_session, admin_user_id: str
) -> uuid.UUID:
    """Insert one normal + one brand-tagged event under a fresh project.

    Returns the project_id.
    """
    pid = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO projects (id, name, engagement_type, created_by, archived)
            VALUES (CAST(:id AS uuid), :name, 'red_team', :created_by, false)
            """
        ),
        {"id": str(pid), "name": f"evt-proj-{pid}", "created_by": admin_user_id},
    )
    # Normal event
    await db_session.execute(
        text(
            """
            INSERT INTO events (
                id, stix_type, project_id, observed_at, title, description,
                content_hash, tags, visibility
            ) VALUES (
                gen_random_uuid(), 'indicator', CAST(:pid AS uuid),
                now(), :title, 'normal event', :hash, :tags, 'shared'
            )
            """
        ),
        {
            "pid": str(pid),
            "title": f"normal-{pid.hex[:8]}",
            "hash": uuid.uuid4().hex,
            "tags": ["rss", "cve"],
        },
    )
    # Brand-monitor event (tagged 'brand-match' by brand_synth)
    await db_session.execute(
        text(
            """
            INSERT INTO events (
                id, stix_type, project_id, observed_at, title, description,
                content_hash, tags, visibility
            ) VALUES (
                gen_random_uuid(), 'indicator', CAST(:pid AS uuid),
                now(), :title, 'brand event', :hash, :tags, 'shared'
            )
            """
        ),
        {
            "pid": str(pid),
            "title": f"brand-{pid.hex[:8]}",
            "hash": uuid.uuid4().hex,
            "tags": ["brand-match", "brand-match:high", f"project:{pid}"],
        },
    )
    await db_session.commit()
    return pid


def _title_matches(items: list[dict], prefix: str) -> list[dict]:
    return [i for i in items if (i.get("title") or "").startswith(prefix)]


@pytest.mark.asyncio
async def test_events_default_excludes_brand_match(events_app, db_session):
    """Default /api/events (no project filter) hides brand-tagged events."""
    app, _factory, admin_user = events_app
    pid = await _seed_project_and_events(db_session, admin_user.id)
    short = pid.hex[:8]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/events?limit=200")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    our_items = [i for i in items if (i.get("title") or "").endswith(short)]
    # Only the 'normal-*' event from our seed should appear; the 'brand-*'
    # event must be excluded by the default include_brand_match=false filter.
    assert len(_title_matches(our_items, "normal-")) == 1
    assert len(_title_matches(our_items, "brand-")) == 0


@pytest.mark.asyncio
async def test_events_include_brand_match_true_includes_them(events_app, db_session):
    """include_brand_match=true surfaces the brand-tagged events."""
    app, _factory, admin_user = events_app
    pid = await _seed_project_and_events(db_session, admin_user.id)
    short = pid.hex[:8]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/events?include_brand_match=true&limit=200")
    assert r.status_code == 200
    items = r.json()["items"]
    our_items = [i for i in items if (i.get("title") or "").endswith(short)]
    assert len(_title_matches(our_items, "normal-")) == 1
    assert len(_title_matches(our_items, "brand-")) == 1


def test_zero_new_webhook_payload_files_for_brand():
    """BRP-05: no new webhook_payloads/*brand* files were added.

    Existing webhook_dispatcher composes payloads from event rows directly;
    brand events ride the generic path via their tag set. Any 'brand*.py' file
    under webhook_payloads would signal new formatter code and violate BRP-05.
    """
    root = pathlib.Path(__file__).resolve().parents[2] / "app" / "services" / "webhook_payloads"
    if not root.exists():
        # Directory does not exist at all → trivially satisfies the "zero-new-code" guarantee.
        return
    offenders = [p for p in root.glob("*brand*") if p.is_file()]
    assert offenders == [], (
        f"BRP-05 violated: new brand-specific webhook formatter files detected: "
        f"{[str(p) for p in offenders]}"
    )


# ---------------------------------------------------------------------------
# Plan 12-12 / BRP-05 — regression guard for events.source_type drift
# ---------------------------------------------------------------------------
# These tests drive brand_monitor._maybe_synth against a real testcontainer
# Postgres so the INSERT column list cannot drift from the events schema
# silently. Prior to Plan 12-12, _EVENT_INSERT_SQL referenced a non-existent
# events.source_type column and every live HIGH-severity synth attempt would
# have raised UndefinedColumn. Unit tests (12-04) mocked the DB and never
# exercised the real INSERT. These two integration tests close that gap.
# ---------------------------------------------------------------------------


async def _seed_project_term_and_match(
    db_session, admin_user_id: str
) -> tuple[uuid.UUID, dict, dict, dict]:
    """Seed a project, a brand_term (domain/active), and a brand_matches row.

    Returns (project_id, term_dict, match_dict, stored_dict) shaped to the
    arguments _maybe_synth expects.
    """
    pid = uuid.uuid4()
    # Project
    await db_session.execute(
        text(
            """
            INSERT INTO projects (id, name, engagement_type, created_by, archived)
            VALUES (CAST(:id AS uuid), :name, 'red_team', :created_by, false)
            """
        ),
        {"id": str(pid), "name": f"synth-proj-{pid}", "created_by": admin_user_id},
    )
    # brand_term — domain, active, not archived
    term_result = await db_session.execute(
        text(
            """
            INSERT INTO brand_terms (id, project_id, term_type, value, mode, archived)
            VALUES (gen_random_uuid(), CAST(:pid AS uuid), 'domain', :value, 'active', false)
            RETURNING id
            """
        ),
        {"pid": str(pid), "value": "example-corp.com"},
    )
    term_id = term_result.scalar_one()

    match_payload = {
        "matched_value": "examp1e-corp.com",
        "match_source": "dnstwist",
        "match_metadata": {"lookup_success": True},
    }

    # brand_matches — severity HIGH, lifecycle 'new', webhook_fired_at NULL
    import json as _json

    match_result = await db_session.execute(
        text(
            """
            INSERT INTO brand_matches (
                id, project_id, brand_term_id, matched_value, match_source,
                severity, match_metadata, first_seen, last_seen, lifecycle_status
            ) VALUES (
                gen_random_uuid(), CAST(:pid AS uuid), CAST(:tid AS uuid),
                :matched_value, :match_source, 'high',
                CAST(:metadata AS jsonb), now(), now(), 'new'
            )
            RETURNING id, webhook_fired_at, first_seen
            """
        ),
        {
            "pid": str(pid),
            "tid": str(term_id),
            "matched_value": match_payload["matched_value"],
            "match_source": match_payload["match_source"],
            "metadata": _json.dumps(match_payload["match_metadata"]),
        },
    )
    match_row = match_result.mappings().one()
    await db_session.commit()

    term = {"id": term_id, "value": "example-corp.com", "term_type": "domain"}
    stored = {
        "id": match_row["id"],
        "webhook_fired_at": match_row["webhook_fired_at"],
        "first_seen": match_row["first_seen"],
    }
    return pid, term, match_payload, stored


@pytest.mark.asyncio
async def test_maybe_synth_inserts_events_row_against_live_postgres(
    events_app, db_session
):
    """BRP-05 end-to-end: _maybe_synth writes an events row + marks match fired.

    Regression guard for plan 12-12: previously _EVENT_INSERT_SQL targeted a
    non-existent events.source_type column; this test would have failed with
    UndefinedColumn.
    """
    from app.services.brand_monitor import _maybe_synth
    from app.services.brand_synth import build_event_dict

    _app, _factory, admin_user = events_app
    pid, term, match, stored = await _seed_project_term_and_match(
        db_session, admin_user.id
    )

    result = await _maybe_synth(
        db_session,
        project_id=pid,
        term=term,
        match=match,
        stored=stored,
        severity="high",
    )
    await db_session.commit()

    assert result is True

    # Compute the content_hash the same way brand_synth does, then look up
    # the events row directly.
    event_dict = build_event_dict(
        match={
            "id": stored["id"],
            "project_id": pid,
            "brand_term_id": term["id"],
            "matched_value": match["matched_value"],
            "match_source": match["match_source"],
            "severity": "high",
            "first_seen": stored["first_seen"],
        },
        term=term,
    )
    expected_hash = event_dict["content_hash"]

    events_result = await db_session.execute(
        text(
            """
            SELECT id, project_id, tags
            FROM events
            WHERE content_hash = :h
            """
        ),
        {"h": expected_hash},
    )
    rows = events_result.mappings().all()
    assert len(rows) == 1, f"expected exactly one synthesised events row, got {len(rows)}"
    row = rows[0]
    assert row["project_id"] == pid

    tags = row["tags"] or []
    assert "brand-match" in tags
    assert "brand-match:high" in tags
    assert f"project:{pid}" in tags

    # webhook_fired_at is now non-NULL for the match
    fired_result = await db_session.execute(
        text("SELECT webhook_fired_at FROM brand_matches WHERE id = :mid"),
        {"mid": stored["id"]},
    )
    fired_at = fired_result.scalar_one()
    assert fired_at is not None


@pytest.mark.asyncio
async def test_maybe_synth_does_not_raise_undefined_column(events_app, db_session):
    """Explicit regression guard: the INSERT must not raise UndefinedColumn.

    Re-introducing `source_type` into either _EVENT_INSERT_SQL or
    brand_synth.build_event_dict would surface as a sqlalchemy ProgrammingError
    here — this is the narrow schema-drift guard.
    """
    from sqlalchemy.exc import ProgrammingError

    from app.services.brand_monitor import _maybe_synth

    _app, _factory, admin_user = events_app
    pid, term, match, stored = await _seed_project_term_and_match(
        db_session, admin_user.id
    )

    try:
        await _maybe_synth(
            db_session,
            project_id=pid,
            term=term,
            match=match,
            stored=stored,
            severity="high",
        )
        await db_session.commit()
    except ProgrammingError as exc:  # pragma: no cover — failure path
        pytest.fail(
            f"_maybe_synth raised ProgrammingError (schema drift regression): {exc}"
        )
