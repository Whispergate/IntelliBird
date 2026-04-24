"""Unit tests for brand_monitor orchestrator (Phase 12 Plan 04 / BRP-02 + BRP-03).

Covers:
- active + non-archived + non-watch-only term filtering
- FTS field-scope branching (short / stoplisted → title+stix_id; long+non-stoplisted → search_tsv)
- CT log branch scope (domain + product only; skips keyword/person)
- dnstwist branch scope (domain only) + batch-of-5 pacing + timeout/error skip semantics
- ON CONFLICT upsert against brand_matches
- severity-threshold-gated synth (HIGH default; MEDIUM when env threshold lowered)
- webhook_fired_at idempotence on re-scan
- subprocess invocation shape
"""
from __future__ import annotations

import os

# Pydantic-settings singleton loads at import time — bootstrap required env vars
# before any app.* import to prevent ValidationError at collection time.
os.environ.setdefault("SECRET_KEY", "x" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "y" * 64)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import json
import subprocess
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# In-memory session fake — records executed SQL + returns queued rows.
# ---------------------------------------------------------------------------
class _ResultShim:
    def __init__(self, rows: list[dict[str, Any]] | None = None, one_row: dict[str, Any] | None = None):
        self._rows = rows or []
        self._one_row = one_row

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def one(self):
        return self._one_row or (self._rows[0] if self._rows else {})

    def first(self):
        if self._one_row is not None:
            return (self._one_row.get("id"),) if "id" in self._one_row else None
        if self._rows:
            r = self._rows[0]
            return (r.get("id"),) if "id" in r else None
        return None


class FakeSession:
    """AsyncSession stand-in. Records executed SQL + parameters and returns
    scripted results based on SQL-text heuristics.
    """

    def __init__(self, *, terms: list[dict[str, Any]], fts_rows: list[dict[str, Any]] | None = None):
        self._terms = terms
        self._fts_rows = fts_rows or []
        self.executions: list[tuple[str, dict[str, Any]]] = []
        self._upsert_counter = 0
        self._scripted_upsert_returns: list[dict[str, Any]] = []

    def queue_upsert_return(self, row: dict[str, Any]) -> None:
        self._scripted_upsert_returns.append(row)

    async def execute(self, stmt, params: dict[str, Any] | None = None):
        # stmt is a sqlalchemy.text(...) clause — normalise to string for inspection
        sql = str(stmt)
        self.executions.append((sql, params or {}))

        if "FROM brand_terms" in sql and "SELECT" in sql:
            return _ResultShim(rows=self._terms)

        if "FROM events" in sql and "SELECT" in sql:
            return _ResultShim(rows=self._fts_rows)

        if "INSERT INTO brand_matches" in sql:
            if self._scripted_upsert_returns:
                row = self._scripted_upsert_returns.pop(0)
            else:
                row = {
                    "id": uuid4(),
                    "webhook_fired_at": None,
                    "first_seen": datetime.now(timezone.utc),
                }
            return _ResultShim(one_row=row)

        if "INSERT INTO events" in sql:
            return _ResultShim(one_row={"id": 42})

        if "UPDATE brand_matches" in sql:
            return _ResultShim()

        return _ResultShim()

    async def commit(self):
        self.executions.append(("COMMIT", {}))


def _term(**overrides):
    base = {
        "id": uuid4(),
        "term_type": "keyword",
        "value": "intellibird",
        "mode": "active",
        "archived": False,
        "high_noise_risk": False,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scan_project_skips_archived_and_watch_only(monkeypatch):
    """The orchestrator's terms query filters mode=active AND archived=false."""
    from app.services import brand_monitor

    session = FakeSession(terms=[])  # SQL filter applied at DB level; session returns []
    await brand_monitor.scan_project(session, uuid4())

    # Confirm the terms SQL carried the expected predicates.
    terms_sql = next(sql for sql, _ in session.executions if "FROM brand_terms" in sql)
    assert "mode = 'active'" in terms_sql
    assert "archived = false" in terms_sql


@pytest.mark.asyncio
async def test_scan_project_fts_branch_short_uses_title_stix_id_only(monkeypatch):
    """Short term (len<6) → FTS SQL uses title+stix_id tsvector, NOT search_tsv."""
    from app.services import brand_monitor

    t = _term(value="api", term_type="keyword")
    session = FakeSession(terms=[t], fts_rows=[])
    # Skip CT (keyword) and dnstwist (non-domain) — FTS only path
    await brand_monitor.scan_project(session, uuid4())

    fts_sqls = [sql for sql, _ in session.executions if "FROM events" in sql and "SELECT" in sql]
    assert fts_sqls, "expected at least one FTS SELECT against events"
    assert "to_tsvector('english', coalesce(title" in fts_sqls[0]
    assert "search_tsv" not in fts_sqls[0]


@pytest.mark.asyncio
async def test_scan_project_fts_branch_long_uses_search_tsv(monkeypatch):
    """Long (len>=6) + non-stoplisted term → uses search_tsv."""
    from app.services import brand_monitor

    t = _term(value="intellibird", term_type="keyword")
    session = FakeSession(terms=[t], fts_rows=[])
    await brand_monitor.scan_project(session, uuid4())

    fts_sqls = [sql for sql, _ in session.executions if "FROM events" in sql and "SELECT" in sql]
    assert fts_sqls
    assert "search_tsv @@ plainto_tsquery" in fts_sqls[0]


@pytest.mark.asyncio
async def test_scan_project_fts_branch_stoplisted_uses_title_stix_id(monkeypatch):
    """A stoplisted term 'core' (len=4, stoplisted) → restricted scope regardless."""
    from app.services import brand_monitor

    t = _term(value="core", term_type="keyword")
    session = FakeSession(terms=[t], fts_rows=[])
    await brand_monitor.scan_project(session, uuid4())

    fts_sqls = [sql for sql, _ in session.executions if "FROM events" in sql and "SELECT" in sql]
    assert fts_sqls
    assert "to_tsvector('english', coalesce(title" in fts_sqls[0]
    assert "search_tsv" not in fts_sqls[0]


@pytest.mark.asyncio
async def test_scan_project_ct_log_only_for_domain_and_product(monkeypatch):
    """crtsh_client.fetch_certs should be called for domain + product, skipped for keyword + person."""
    from app.services import brand_monitor

    calls: list[str] = []

    async def fake_fetch(term_value, **kw):
        calls.append(term_value)
        return []

    monkeypatch.setattr(brand_monitor, "fetch_certs", fake_fetch)

    terms = [
        _term(value="intellibird", term_type="keyword"),
        _term(value="intellibird.io", term_type="domain"),
        _term(value="product-alpha", term_type="product"),
        _term(value="jane_doe", term_type="person"),
    ]
    session = FakeSession(terms=terms, fts_rows=[])
    await brand_monitor.scan_project(session, uuid4())

    assert "intellibird.io" in calls
    assert "product-alpha" in calls
    assert "intellibird" not in calls
    assert "jane_doe" not in calls


@pytest.mark.asyncio
async def test_scan_project_dnstwist_only_for_domain(monkeypatch):
    """Only domain-type terms get passed to dnstwist subprocess batches."""
    from app.services import brand_monitor

    subprocess_calls: list[list[str]] = []

    def fake_run(cmd, **kw):
        subprocess_calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")

    monkeypatch.setattr(brand_monitor.subprocess, "run", fake_run)

    async def fake_fetch(term_value, **kw):
        return []

    monkeypatch.setattr(brand_monitor, "fetch_certs", fake_fetch)

    terms = [
        _term(value="intellibird.io", term_type="domain"),
        _term(value="product-alpha", term_type="product"),
        _term(value="keyword-x", term_type="keyword"),
    ]
    session = FakeSession(terms=terms, fts_rows=[])
    await brand_monitor.scan_project(session, uuid4())

    dnstwist_targets = [cmd[-1] for cmd in subprocess_calls if cmd and cmd[0] == "dnstwist"]
    assert dnstwist_targets == ["intellibird.io"]


@pytest.mark.asyncio
async def test_scan_project_dnstwist_batch_of_5(monkeypatch):
    """12 domain terms → 3 batches (5,5,2) → asyncio.sleep called 2 times between batches."""
    from app.services import brand_monitor

    terms = [_term(value=f"d{i}.example", term_type="domain") for i in range(12)]

    def fake_run(cmd, **kw):
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")

    monkeypatch.setattr(brand_monitor.subprocess, "run", fake_run)

    async def fake_fetch(term_value, **kw):
        return []

    monkeypatch.setattr(brand_monitor, "fetch_certs", fake_fetch)

    sleep_calls: list[float] = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(brand_monitor.asyncio, "sleep", fake_sleep)

    session = FakeSession(terms=terms, fts_rows=[])
    await brand_monitor.scan_project(session, uuid4())

    # 12 terms → batches of 5+5+2 → sleep between batch 1→2 and 2→3 (but not after final)
    assert len(sleep_calls) == 2
    assert all(s == brand_monitor.DNSTWIST_BATCH_SLEEP_SECONDS for s in sleep_calls)


@pytest.mark.asyncio
async def test_scan_project_dnstwist_timeout_skips_term(monkeypatch, caplog):
    """subprocess.TimeoutExpired → term skipped + warning log 'brand_dnstwist_timeout'."""
    import logging

    from app.services import brand_monitor

    t = _term(value="intellibird.io", term_type="domain")

    def fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=120)

    monkeypatch.setattr(brand_monitor.subprocess, "run", fake_run)

    async def fake_fetch(term_value, **kw):
        return []

    monkeypatch.setattr(brand_monitor, "fetch_certs", fake_fetch)

    session = FakeSession(terms=[t], fts_rows=[])
    with caplog.at_level(logging.WARNING, logger="app.services.brand_monitor"):
        stats = await brand_monitor.scan_project(session, uuid4())

    assert any("brand_dnstwist_timeout" in rec.message for rec in caplog.records)
    # scan should complete (not raise) — stats returned
    assert isinstance(stats, dict)


@pytest.mark.asyncio
async def test_scan_project_dnstwist_calledprocesserror_skips_term(monkeypatch, caplog):
    """CalledProcessError → skip + log 'brand_dnstwist_error'."""
    import logging

    from app.services import brand_monitor

    t = _term(value="intellibird.io", term_type="domain")

    def fake_run(cmd, **kw):
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd)

    monkeypatch.setattr(brand_monitor.subprocess, "run", fake_run)

    async def fake_fetch(term_value, **kw):
        return []

    monkeypatch.setattr(brand_monitor, "fetch_certs", fake_fetch)

    session = FakeSession(terms=[t], fts_rows=[])
    with caplog.at_level(logging.WARNING, logger="app.services.brand_monitor"):
        await brand_monitor.scan_project(session, uuid4())

    assert any("brand_dnstwist_error" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_scan_project_match_insert_upsert(monkeypatch):
    """Match INSERT uses ON CONFLICT DO UPDATE keyed on (project_id, brand_term_id, matched_value, match_source)."""
    from app.services import brand_monitor

    t = _term(value="intellibird", term_type="keyword")
    fts_rows = [{"id": 100, "title": "Hit 1", "stix_id": "indicator--abc"}]
    session = FakeSession(terms=[t], fts_rows=fts_rows)
    await brand_monitor.scan_project(session, uuid4())

    insert_sqls = [sql for sql, _ in session.executions if "INSERT INTO brand_matches" in sql]
    assert insert_sqls, "expected brand_matches INSERT"
    assert "ON CONFLICT (project_id, brand_term_id, matched_value, match_source)" in insert_sqls[0]
    assert "DO UPDATE SET last_seen" in insert_sqls[0]


@pytest.mark.asyncio
async def test_scan_project_severity_high_triggers_synth(monkeypatch):
    """dnstwist+success=HIGH with webhook_fired_at=NULL → build_event_dict called."""
    from app.services import brand_monitor

    t = _term(value="intellibird.io", term_type="domain")

    def fake_run(cmd, **kw):
        payload = [{
            "fuzzer": "homoglyph",
            "domain": "intel1ibird.io",
            "dns_a": ["1.2.3.4"],
            "dns_aaaa": [],
            "dns_mx": [],
            "dns_ns": ["ns1.x.com"],
        }]
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(brand_monitor.subprocess, "run", fake_run)

    async def fake_fetch(term_value, **kw):
        return []

    monkeypatch.setattr(brand_monitor, "fetch_certs", fake_fetch)

    called = []

    def fake_build_event_dict(*, match, term):
        called.append((match, term))
        return {
            "source_type": "brand-monitor",
            "stix_type": "indicator",
            "stix_id": "indicator--x",
            "title": "t",
            "description": "d",
            "observed_at": datetime.now(timezone.utc),
            "tags": [],
            "content_hash": "h" * 64,
            "raw_stix": {"type": "indicator"},
            "project_id": uuid4(),
        }

    monkeypatch.setattr(brand_monitor, "build_event_dict", fake_build_event_dict)

    session = FakeSession(terms=[t])
    # Force BRAND_WEBHOOK_SEVERITY_THRESHOLD to HIGH explicitly
    monkeypatch.setattr(brand_monitor.settings, "BRAND_WEBHOOK_SEVERITY_THRESHOLD", "HIGH", raising=False)

    await brand_monitor.scan_project(session, uuid4())

    assert called, "build_event_dict should have been called for HIGH severity dnstwist success"


@pytest.mark.asyncio
async def test_scan_project_severity_medium_does_not_synth(monkeypatch):
    """ct_log match = MEDIUM; default threshold HIGH → build_event_dict NOT called."""
    from app.services import brand_monitor

    t = _term(value="intellibird.io", term_type="domain")

    async def fake_fetch(term_value, **kw):
        return [{
            "matched_value": "evil-intellibird.io",
            "not_before": "2026-04-20T00:00:00",
            "issuer_name": "LE",
            "min_cert_id": 1,
        }]

    monkeypatch.setattr(brand_monitor, "fetch_certs", fake_fetch)

    def fake_run(cmd, **kw):
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")

    monkeypatch.setattr(brand_monitor.subprocess, "run", fake_run)

    called = []

    def fake_build_event_dict(**kw):
        called.append(kw)
        return {}

    monkeypatch.setattr(brand_monitor, "build_event_dict", fake_build_event_dict)

    session = FakeSession(terms=[t])
    monkeypatch.setattr(brand_monitor.settings, "BRAND_WEBHOOK_SEVERITY_THRESHOLD", "HIGH", raising=False)

    await brand_monitor.scan_project(session, uuid4())

    assert called == [], "MEDIUM match must not synth when threshold=HIGH"


@pytest.mark.asyncio
async def test_scan_project_severity_medium_synths_when_threshold_medium(monkeypatch):
    """When BRAND_WEBHOOK_SEVERITY_THRESHOLD='MEDIUM', ct_log match synths event."""
    from app.services import brand_monitor

    t = _term(value="intellibird.io", term_type="domain")

    async def fake_fetch(term_value, **kw):
        return [{
            "matched_value": "evil-intellibird.io",
            "not_before": "2026-04-20T00:00:00",
            "issuer_name": "LE",
            "min_cert_id": 1,
        }]

    monkeypatch.setattr(brand_monitor, "fetch_certs", fake_fetch)

    def fake_run(cmd, **kw):
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")

    monkeypatch.setattr(brand_monitor.subprocess, "run", fake_run)

    called = []

    def fake_build_event_dict(*, match, term):
        called.append((match, term))
        return {
            "source_type": "brand-monitor",
            "stix_type": "indicator",
            "stix_id": "indicator--x",
            "title": "t",
            "description": "d",
            "observed_at": datetime.now(timezone.utc),
            "tags": [],
            "content_hash": "h" * 64,
            "raw_stix": {"type": "indicator"},
            "project_id": uuid4(),
        }

    monkeypatch.setattr(brand_monitor, "build_event_dict", fake_build_event_dict)

    session = FakeSession(terms=[t])
    monkeypatch.setattr(brand_monitor.settings, "BRAND_WEBHOOK_SEVERITY_THRESHOLD", "MEDIUM", raising=False)

    await brand_monitor.scan_project(session, uuid4())

    assert called, "MEDIUM match must synth when threshold=MEDIUM"


@pytest.mark.asyncio
async def test_scan_project_webhook_fired_at_prevents_resynth(monkeypatch):
    """Match row already has webhook_fired_at → build_event_dict NOT called."""
    from app.services import brand_monitor

    t = _term(value="intellibird.io", term_type="domain")

    def fake_run(cmd, **kw):
        payload = [{
            "fuzzer": "homoglyph",
            "domain": "intel1ibird.io",
            "dns_a": ["1.2.3.4"],
            "dns_aaaa": [],
            "dns_mx": [],
            "dns_ns": ["ns1.x.com"],
        }]
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(brand_monitor.subprocess, "run", fake_run)

    async def fake_fetch(term_value, **kw):
        return []

    monkeypatch.setattr(brand_monitor, "fetch_certs", fake_fetch)

    called = []

    def fake_build_event_dict(**kw):
        called.append(kw)
        return {}

    monkeypatch.setattr(brand_monitor, "build_event_dict", fake_build_event_dict)

    session = FakeSession(terms=[t])
    # Pre-load the upsert return with webhook_fired_at set
    session.queue_upsert_return({
        "id": uuid4(),
        "webhook_fired_at": datetime.now(timezone.utc),
        "first_seen": datetime.now(timezone.utc),
    })
    monkeypatch.setattr(brand_monitor.settings, "BRAND_WEBHOOK_SEVERITY_THRESHOLD", "HIGH", raising=False)

    await brand_monitor.scan_project(session, uuid4())

    assert called == [], "webhook_fired_at set → must not re-synth"


@pytest.mark.asyncio
async def test_scan_project_sync_subprocess_called_with_expected_args(monkeypatch):
    """subprocess.run invoked with dnstwist + --threads 10 + --format json + timeout=120 + capture_output."""
    from app.services import brand_monitor

    t = _term(value="intellibird.io", term_type="domain")

    captured: dict[str, Any] = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["kwargs"] = kw
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")

    monkeypatch.setattr(brand_monitor.subprocess, "run", fake_run)

    async def fake_fetch(term_value, **kw):
        return []

    monkeypatch.setattr(brand_monitor, "fetch_certs", fake_fetch)

    session = FakeSession(terms=[t])
    await brand_monitor.scan_project(session, uuid4())

    assert captured["cmd"][0] == "dnstwist"
    assert "--threads" in captured["cmd"]
    assert "10" in captured["cmd"]
    assert "--format" in captured["cmd"]
    assert "json" in captured["cmd"]
    assert captured["cmd"][-1] == "intellibird.io"
    assert captured["kwargs"].get("timeout") == 120
    assert captured["kwargs"].get("capture_output") is True
