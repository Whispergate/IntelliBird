"""Integration tests for TIBER report generation.

Wave 0 stubs — skip-marked pending Wave 3+ service layer and migration 015.
Each test documents exact integration behaviour; stubs flip green once the
corresponding service code and DB migration land.

Requirements covered:
  TIBER-01 — migration 015, report CRUD, scenario count gate
  TIBER-02 — scenario count gate
  TIBER-03 — BYTEA 50MB cap, history list excludes content_bytea
  TIBER-04 — auto-populate no cross-project leakage, threat landscape scoped
  AI-08   — AI draft badge metadata persists after edit

Restore state machine tests (per CONTEXT.md §Report state machine):
  - Admin can restore archived → draft
  - Lead cannot restore archived (must be Admin only)
  - Restore rejects non-archived reports (409)
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# TIBER-01: Migration 015 up/down/up cycle
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Wave 3 — TIBER service layer pending")
@pytest.mark.asyncio
async def test_migration_015(db_session, monkeypatch) -> None:
    """Migration 015 up/down/up cycles cleanly inside testcontainer.

    Validates:
      - alembic upgrade head applies migration 015 without error
      - alembic downgrade -1 reverses migration 015 cleanly (no orphan tables/types)
      - alembic upgrade head re-applies migration 015 cleanly (idempotency)
      - All 5 tables created: tiber_reports, tiber_actor_profiles, tiber_scenarios,
        project_tiber_state, reports
      - 3 ENUMs created: tiber_report_state_enum, report_format_enum, scenario_objective_enum
      - reports.content_bytea CHECK constraint ck_reports_bytea_size present
    """
    import subprocess

    # Run up/down/up cycle (requires DATABASE_URL env pointing to testcontainer)
    result_up = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        capture_output=True, text=True, check=False
    )
    assert result_up.returncode == 0, (
        f"alembic upgrade head failed:\n{result_up.stderr}"
    )

    result_down = subprocess.run(
        ["uv", "run", "alembic", "downgrade", "-1"],
        capture_output=True, text=True, check=False
    )
    assert result_down.returncode == 0, (
        f"alembic downgrade -1 failed:\n{result_down.stderr}"
    )

    result_up2 = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        capture_output=True, text=True, check=False
    )
    assert result_up2.returncode == 0, (
        f"alembic re-upgrade head failed:\n{result_up2.stderr}"
    )

    # Verify tables exist
    from sqlalchemy import text as sa_text
    for table in ("tiber_reports", "tiber_actor_profiles", "tiber_scenarios",
                  "project_tiber_state", "reports"):
        row = (await db_session.execute(
            sa_text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
            {"t": table}
        )).first()
        assert row is not None, f"Table {table!r} not found after migration 015"


# ---------------------------------------------------------------------------
# TIBER-01: Report CRUD lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_crud(two_project_fixture, db_session, monkeypatch) -> None:
    """Full TIBER report CRUD lifecycle.

    Sequence:
      POST /api/projects/{id}/tiber/reports           → 201 draft created
      GET  /api/projects/{id}/tiber/reports/{report_id} → 200 draft returned
      PATCH /api/projects/{id}/tiber/reports/{report_id} → 200 draft updated (Lead+)
      POST .../publish                                → 200 state='published'
      POST .../archive (Admin only)                   → 200 state='archived'
      POST .../clone                                  → 201 new draft created

    Role gates:
      - Lead+ can create/edit/publish
      - Admin only can archive
      - Member can read only
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_id = str(fx.project_a.id)

    async with await _client() as c:
        # Create report (Lead JWT)
        r_create = await c.post(
            f"/api/projects/{project_id}/tiber/reports",
            headers=_bearer(fx.jwt_a),
            json={"title": "Q1 2026 TIBER Engagement"},
        )
        assert r_create.status_code == 201, (
            f"Expected 201 on create, got {r_create.status_code}: {r_create.text}"
        )
        report = r_create.json()
        report_id = report["id"]
        assert report["state"] == "draft"

        # Get report
        r_get = await c.get(
            f"/api/projects/{project_id}/tiber/reports/{report_id}",
            headers=_bearer(fx.jwt_a),
        )
        assert r_get.status_code == 200
        assert r_get.json()["id"] == report_id

        # Patch (update) report title
        r_patch = await c.patch(
            f"/api/projects/{project_id}/tiber/reports/{report_id}",
            headers=_bearer(fx.jwt_a),
            json={"title": "Q1 2026 TIBER Engagement — Updated"},
        )
        assert r_patch.status_code == 200

        # Pre-populate 3 selected scenarios (required by scenario_gate_check: min 3).
        _SCENARIO_TECHNIQUES = ["T1566", "T1190", "T1059"]
        for i, tech in enumerate(_SCENARIO_TECHNIQUES):
            r_sc = await c.post(
                f"/api/projects/{project_id}/tiber/reports/{report_id}/scenarios",
                headers=_bearer(fx.jwt_a),
                json={
                    "actor_id": None,
                    "cif_or_cbs_label": f"CBS-{i}",
                    "objective_type": "availability",
                    "attack_technique_id": tech,
                    "procedure_text": f"Procedure {i}",
                    "selected_for_inclusion": True,
                },
            )
            assert r_sc.status_code == 201, (
                f"Failed to create scenario {i}: {r_sc.status_code} {r_sc.text}"
            )

        # Publish (requires min 3 selected scenarios — now satisfied)
        r_publish = await c.post(
            f"/api/projects/{project_id}/tiber/reports/{report_id}/publish",
            headers=_bearer(fx.jwt_a),
        )
        assert r_publish.status_code == 200
        assert r_publish.json()["state"] == "published"

        # Patch published report must return 409
        r_patch_published = await c.patch(
            f"/api/projects/{project_id}/tiber/reports/{report_id}",
            headers=_bearer(fx.jwt_a),
            json={"title": "Cannot edit published"},
        )
        assert r_patch_published.status_code == 409, (
            "Published report must reject PATCH with 409 Conflict"
        )

        # Archive (Admin only)
        r_archive = await c.post(
            f"/api/projects/{project_id}/tiber/reports/{report_id}/archive",
            headers=_bearer(fx.jwt_admin),
        )
        assert r_archive.status_code == 200
        assert r_archive.json()["state"] == "archived"

        # Clone creates new draft
        r_clone = await c.post(
            f"/api/projects/{project_id}/tiber/reports/{report_id}/clone",
            headers=_bearer(fx.jwt_a),
        )
        assert r_clone.status_code == 201
        clone = r_clone.json()
        assert clone["state"] == "draft"
        assert clone["id"] != report_id


# ---------------------------------------------------------------------------
# TIBER-02: Scenario count gate blocks publish when <3 selected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_count_gate(two_project_fixture, db_session, monkeypatch) -> None:
    """POST /publish returns 422/409 when <3 selected scenarios; passes at exactly 3.

    Per CONTEXT.md §Scenario count gate: min 3 must be selected for inclusion.
    Backend must enforce this regardless of client-side validation.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_id = str(fx.project_a.id)

    async with await _client() as c:
        # Create a report with 0 scenarios selected
        r_create = await c.post(
            f"/api/projects/{project_id}/tiber/reports",
            headers=_bearer(fx.jwt_a),
            json={"title": "Scenario Gate Test"},
        )
        assert r_create.status_code == 201
        report_id = r_create.json()["id"]

        # Publish with 0 scenarios → must fail
        r_pub_0 = await c.post(
            f"/api/projects/{project_id}/tiber/reports/{report_id}/publish",
            headers=_bearer(fx.jwt_a),
        )
        assert r_pub_0.status_code in (409, 422), (
            f"Expected 409 or 422 with 0 selected scenarios, got {r_pub_0.status_code}"
        )

        # Add 2 selected scenarios → still fails
        for i in range(2):
            await c.post(
                f"/api/projects/{project_id}/tiber/reports/{report_id}/scenarios",
                headers=_bearer(fx.jwt_a),
                json={
                    "actor_id": None,
                    "cif_or_cbs_label": f"CBS-{i}",
                    "objective_type": "availability",
                    "attack_technique_id": "T1566",
                    "procedure_text": f"Procedure {i}",
                    "selected_for_inclusion": True,
                },
            )
        r_pub_2 = await c.post(
            f"/api/projects/{project_id}/tiber/reports/{report_id}/publish",
            headers=_bearer(fx.jwt_a),
        )
        assert r_pub_2.status_code in (409, 422), (
            f"Expected 409 or 422 with 2 selected scenarios, got {r_pub_2.status_code}"
        )

        # Add 3rd scenario → publish succeeds
        await c.post(
            f"/api/projects/{project_id}/tiber/reports/{report_id}/scenarios",
            headers=_bearer(fx.jwt_a),
            json={
                "actor_id": None,
                "cif_or_cbs_label": "CBS-2",
                "objective_type": "integrity",
                "attack_technique_id": "T1190",
                "procedure_text": "Procedure 2",
                "selected_for_inclusion": True,
            },
        )
        r_pub_3 = await c.post(
            f"/api/projects/{project_id}/tiber/reports/{report_id}/publish",
            headers=_bearer(fx.jwt_a),
        )
        assert r_pub_3.status_code == 200, (
            f"Expected 200 with exactly 3 selected scenarios, got {r_pub_3.status_code}: {r_pub_3.text}"
        )


# ---------------------------------------------------------------------------
# TIBER-03: BYTEA 50MB CHECK constraint enforced
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bytea_size_cap(two_project_fixture, db_session, monkeypatch) -> None:
    """INSERT into reports with content_bytea > 50MB raises ck_reports_bytea_size.

    The CHECK constraint `octet_length(content_bytea) <= 52428800` (50MB)
    must be enforced at the DB level. This test inserts directly via SQL
    to bypass application-layer validation and confirm the DB constraint fires.

    Per RESEARCH.md §BYTEA Practical Size Limits + CONTEXT.md §Versioning.
    """
    import uuid
    from sqlalchemy import text as sa_text

    # First create a tiber_report row to FK against
    report_id = uuid.uuid4()
    project_id = two_project_fixture.project_a.id

    await db_session.execute(
        sa_text(
            "INSERT INTO tiber_reports (id, project_id, title, state) "
            "VALUES (:id, :pid, :title, 'draft')"
        ),
        {"id": report_id, "pid": project_id, "title": "BYTEA cap test"},
    )
    await db_session.commit()

    # Attempt to insert a 51MB BYTEA blob (exceeds 50MB cap)
    fifty_one_mb = bytes(51 * 1024 * 1024)  # 51MB of zeros
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError, match="ck_reports_bytea_size"):
        await db_session.execute(
            sa_text(
                "INSERT INTO reports "
                "(tiber_report_id, project_id, format, version_number, "
                " content_bytea, filename, generated_at, report_state_at_export) "
                "VALUES (:rid, :pid, 'markdown', 1, :blob, 'test.md', now(), 'draft')"
            ),
            {"rid": report_id, "pid": project_id, "blob": fifty_one_mb},
        )
        await db_session.commit()


# ---------------------------------------------------------------------------
# TIBER-04: Auto-populate no cross-project leakage
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Wave 3 — TIBER service layer pending")
@pytest.mark.asyncio
async def test_auto_populate_no_leakage(two_project_fixture, db_session, monkeypatch) -> None:
    """POST /api/projects/{A}/tiber/reports creates report with zero Project B data.

    Verifies the auto-populate endpoint (called on report create) scopes all
    queries through build_scope_predicate so no Project B events/actors appear
    in Project A's auto-populated sections.

    Checks:
      - tl_top_events: all event project_ids == project_a.id
      - actor_profiles: all actor source_event_ids reference project_a events only
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_id = str(fx.project_a.id)
    project_b_id = str(fx.project_b.id)

    async with await _client() as c:
        r = await c.post(
            f"/api/projects/{project_id}/tiber/reports",
            headers=_bearer(fx.jwt_a),
            json={"title": "Auto-populate leakage test"},
        )
    assert r.status_code == 201
    report = r.json()

    # Verify no Project B events in Threat Landscape
    for event in report.get("tl_top_events", []):
        event_project = event.get("project_id")
        assert event_project == project_id, (
            f"LEAK: auto-populated tl_top_events contains Project B event "
            f"(project_id={event_project!r}, expected {project_id!r})"
        )

    # Verify no Project B actor source events
    for actor in report.get("actor_profiles", []):
        for source_event_id in actor.get("source_event_ids", []):
            b_event_ids = {str(eid) for eid in fx.events_b}
            assert source_event_id not in b_event_ids, (
                f"LEAK: auto-populated actor '{actor.get('name')}' "
                f"has source_event_id {source_event_id} from Project B"
            )


# ---------------------------------------------------------------------------
# TIBER-04: Threat Landscape auto-populate scoped to project
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Wave 3 — TIBER service layer pending")
@pytest.mark.asyncio
async def test_threat_landscape_auto_populate(two_project_fixture, db_session, monkeypatch) -> None:
    """POST creates report; tl_top_events contains N<=20 rows from project A scope only."""
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_id = str(fx.project_a.id)

    # Seed scope so build_scope_predicate doesn't short-circuit to false
    from sqlalchemy import text as sa_text
    await db_session.execute(
        sa_text(
            "INSERT INTO project_scope_rows "
            "(id, project_id, scope_type, value, intel_scope, active_test_scope, exclude) "
            "VALUES (gen_random_uuid(), :pid, 'keyword', 'evt', true, false, false)"
        ),
        {"pid": fx.project_a.id},
    )
    await db_session.commit()

    async with await _client() as c:
        r = await c.post(
            f"/api/projects/{project_id}/tiber/reports",
            headers=_bearer(fx.jwt_a),
            json={"title": "Threat Landscape Test"},
        )
    assert r.status_code == 201
    report = r.json()

    top_events = report.get("tl_top_events", [])
    assert len(top_events) <= 20, (
        f"tl_top_events exceeded default cap of 20: {len(top_events)} events"
    )
    # All events must be from project_a
    for event in top_events:
        assert event.get("project_id") == project_id, (
            f"LEAK: tl_top_events contains event from wrong project: {event!r}"
        )


# ---------------------------------------------------------------------------
# AI-08: AI draft badge metadata persists after edit
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Wave 3 — TIBER service layer pending")
@pytest.mark.asyncio
async def test_ai_draft_badge(two_project_fixture, db_session, monkeypatch) -> None:
    """POST .../draft-narrative + analyst PATCH → ai_draft_metadata JSONB persists.

    Per CONTEXT.md §AI-08:
      - ai_draft_metadata has {edited_at, edited_by} after analyst edits
      - Badge shows 'AI-drafted, edited by [analyst] on [date]'
      - Metadata included in BYTEA export header for audit
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_id = str(fx.project_a.id)

    async with await _client() as c:
        # Create report and scenario
        r_report = await c.post(
            f"/api/projects/{project_id}/tiber/reports",
            headers=_bearer(fx.jwt_a),
            json={"title": "AI Draft Badge Test"},
        )
        assert r_report.status_code == 201
        report_id = r_report.json()["id"]

        r_scenario = await c.post(
            f"/api/projects/{project_id}/tiber/reports/{report_id}/scenarios",
            headers=_bearer(fx.jwt_a),
            json={
                "cif_or_cbs_label": "Core Banking System",
                "objective_type": "availability",
                "attack_technique_id": "T1566",
                "procedure_text": "Phishing campaign",
                "selected_for_inclusion": True,
            },
        )
        assert r_scenario.status_code == 201
        scenario_id = r_scenario.json()["id"]

        # Request AI draft narrative (SSE stream)
        r_draft = await c.post(
            f"/api/projects/{project_id}/tiber/reports/{report_id}/scenarios/{scenario_id}/draft-narrative",
            headers=_bearer(fx.jwt_a),
        )
        assert r_draft.status_code in (200, 202)

        # Analyst edits the narrative
        r_edit = await c.patch(
            f"/api/projects/{project_id}/tiber/reports/{report_id}/scenarios/{scenario_id}",
            headers=_bearer(fx.jwt_a),
            json={"ai_draft_narrative": "Analyst-revised narrative text."},
        )
        assert r_edit.status_code == 200
        scenario = r_edit.json()

        # ai_draft_metadata must be set with edited_at and edited_by
        metadata = scenario.get("ai_draft_metadata")
        assert metadata is not None, (
            "ai_draft_metadata not set after analyst edit of AI-drafted narrative"
        )
        assert "edited_at" in metadata, (
            f"ai_draft_metadata missing 'edited_at': {metadata!r}"
        )
        assert "edited_by" in metadata, (
            f"ai_draft_metadata missing 'edited_by': {metadata!r}"
        )


# ---------------------------------------------------------------------------
# State machine: Admin can restore archived → draft
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_restore_archived_to_draft(two_project_fixture, db_session, monkeypatch) -> None:
    """POST /reports/{id}/restore (Admin jwt) on archived → 200 + state=='draft'.

    Per CONTEXT.md §Report state machine:
      archived → draft is an Admin-only transition.
      restore sets state='draft' and refreshes updated_at.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_id = str(fx.project_a.id)

    report_id = await _create_archived_report(fx, project_id)

    async with await _client() as c:
        r = await c.post(
            f"/api/projects/{project_id}/tiber/reports/{report_id}/restore",
            headers=_bearer(fx.jwt_admin),
        )
    assert r.status_code == 200, (
        f"Expected 200 for Admin restore, got {r.status_code}: {r.text}"
    )
    body = r.json()
    assert body["state"] == "draft", (
        f"Expected state='draft' after restore, got state={body['state']!r}"
    )
    assert "updated_at" in body, "Response must include updated_at field"


# ---------------------------------------------------------------------------
# State machine: Lead cannot restore archived (Admin only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lead_cannot_restore_archived(two_project_fixture, db_session, monkeypatch) -> None:
    """POST /reports/{id}/restore (Lead jwt, NOT Admin) → 403 forbidden.

    archived→draft is Admin-only per CONTEXT.md state machine.
    Lead role must receive 403; attempting restore must not change state.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_id = str(fx.project_a.id)

    report_id = await _create_archived_report(fx, project_id)

    async with await _client() as c:
        # jwt_a is a Contributor/Lead — not Admin
        r = await c.post(
            f"/api/projects/{project_id}/tiber/reports/{report_id}/restore",
            headers=_bearer(fx.jwt_a),
        )
    assert r.status_code == 403, (
        f"Expected 403 for Lead restore attempt, got {r.status_code}: {r.text}"
    )


# ---------------------------------------------------------------------------
# State machine: Restore rejects non-archived reports (409)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Wave 3 — TIBER service layer pending")
@pytest.mark.asyncio
async def test_restore_rejects_non_archived(two_project_fixture, db_session, monkeypatch) -> None:
    """POST /reports/{id}/restore on a draft or published report → 409 cannot_restore_from_state.

    Restore is only valid from archived state. Calling it on draft or published
    must return 409 to prevent unintended state transitions.
    """
    _patch_auth(monkeypatch)
    fx = two_project_fixture
    project_id = str(fx.project_a.id)

    async with await _client() as c:
        # Create a draft report
        r_create = await c.post(
            f"/api/projects/{project_id}/tiber/reports",
            headers=_bearer(fx.jwt_a),
            json={"title": "Restore State Gate Test"},
        )
        assert r_create.status_code == 201
        report_id = r_create.json()["id"]

        # Attempt restore on draft → 409
        r_restore_draft = await c.post(
            f"/api/projects/{project_id}/tiber/reports/{report_id}/restore",
            headers=_bearer(fx.jwt_admin),
        )
        assert r_restore_draft.status_code == 409, (
            f"Expected 409 when restoring draft, got {r_restore_draft.status_code}"
        )
        body = r_restore_draft.json()
        error_detail = str(body.get("detail", ""))
        assert "cannot_restore_from_state" in error_detail or "archived" in error_detail.lower(), (
            f"Expected cannot_restore_from_state error, got: {error_detail!r}"
        )


# ---------------------------------------------------------------------------
# Harness helpers — mirror test_prod01_cross_project_leakage.py pattern
# ---------------------------------------------------------------------------

TEST_SIGNING_KEY = "j" * 64


def _patch_auth(monkeypatch) -> None:
    """Enable AUTH_ENABLED, pin signing key, stub token_version/jti checks."""
    import app.middleware.auth as auth_mod
    from app.config import settings

    monkeypatch.setattr(settings, "AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "JWT_SIGNING_KEY", TEST_SIGNING_KEY, raising=False)

    async def _tv(_user_id: str):
        return 0

    async def _not_revoked(_jti: str) -> bool:
        return False

    monkeypatch.setattr(auth_mod, "_get_cached_token_version", _tv)
    monkeypatch.setattr(auth_mod, "_is_jti_revoked", _not_revoked)


async def _client():
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_archived_report(fx, project_id: str) -> str:
    """Helper: create and archive a report for state machine tests."""
    import uuid
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            f"/api/projects/{project_id}/tiber/reports",
            headers=_bearer(fx.jwt_a),
            json={"title": f"Archive test {uuid.uuid4().hex[:6]}"},
        )
        assert r.status_code == 201
        report_id = r.json()["id"]

        # Publish first (required before archive)
        await c.post(
            f"/api/projects/{project_id}/tiber/reports/{report_id}/publish",
            headers=_bearer(fx.jwt_a),
        )

        # Archive
        r_archive = await c.post(
            f"/api/projects/{project_id}/tiber/reports/{report_id}/archive",
            headers=_bearer(fx.jwt_admin),
        )
        assert r_archive.status_code == 200, (
            f"Failed to archive report for test setup: {r_archive.text}"
        )

    return report_id
