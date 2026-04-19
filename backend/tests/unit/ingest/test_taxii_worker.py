"""TAXII/STIX parser + TLP resolver + worker tests — INGT-01..04.

Parser-level (Task 1): pure parse_stix_bundle + resolve_tlp_marking +
normalise_stix_object against the captured taxii_mitre_sample.json fixture.
Worker-level (Task 2): mocks taxii2-client Server + stix2.parse and asserts
pagination loop, cursor commit order, allow_custom=True, TLP
resolution end-to-end.
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "taxii_mitre_sample.json"
SRC_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")

# Canonical TLP UUIDs seeded in migration 001:
TLP_AMBER = uuid.UUID("f88d31f6-1208-47b8-8c13-1706eb6387bc")
TLP_GREEN = uuid.UUID("34098fce-860f-48ae-8e50-ebd3cc5e41da")
TLP_RED = uuid.UUID("5e57c739-391a-4eb3-b6be-7d15ca92d5ed")
TLP_CLEAR = uuid.UUID("613f2e26-407d-48c7-9eca-b8e91df99dc9")

TLP_CACHE = {
    TLP_CLEAR: "TLP:CLEAR",
    TLP_GREEN: "TLP:GREEN",
    TLP_AMBER: "TLP:AMBER",
    TLP_RED: "TLP:RED",
}


def _fixture_objects() -> list[dict]:
    raw = json.loads(FIXTURE.read_text())
    return raw["objects"]


# ───────────────────── Parser-level (Task 1) ─────────────────────

def test_parse_bundle_allows_custom() -> None:
    from app.ingest.taxii_parser import parse_stix_bundle
    bundle = {
        "type": "bundle",
        "id": "bundle--1cf6c40f-c9fb-4e35-8b29-3a1a91a8b6b4",
        "objects": [
            {
                "type": "x-misp-attribute",
                "id": "x-misp-attribute--11111111-1111-1111-1111-111111111111",
                "spec_version": "2.1",
                "created": "2026-01-01T00:00:00.000Z",
                "modified": "2026-01-01T00:00:00.000Z",
            }
        ],
    }
    objs = parse_stix_bundle(bundle)
    assert objs  # Either a list of dicts or a list of stix2 objects — truthy
    assert len(objs) == 1


def test_parse_bundle_rejects_invalid_non_custom() -> None:
    from app.ingest.taxii_parser import parse_stix_bundle
    bundle = {
        "type": "bundle",
        "id": "bundle--22222222-2222-2222-2222-222222222222",
        "objects": [{"type": "indicator", "id": "not-a-valid-stix-id"}],
    }
    with pytest.raises(Exception):  # stix2.exceptions.* or STIXError
        parse_stix_bundle(bundle)


def test_tlp_canonical_uuids_resolve() -> None:
    from app.ingest.taxii_parser import resolve_tlp_marking
    result = resolve_tlp_marking(
        [f"marking-definition--{TLP_AMBER}"], TLP_CACHE
    )
    assert result == TLP_AMBER


def test_tlp_non_canonical_returns_none(caplog: pytest.LogCaptureFixture) -> None:
    from app.ingest.taxii_parser import resolve_tlp_marking
    with caplog.at_level("WARNING"):
        result = resolve_tlp_marking(
            ["marking-definition--00000000-0000-0000-0000-deadbeefdead"], TLP_CACHE
        )
    assert result is None
    assert any("tlp_marking_unresolved" in rec.getMessage() for rec in caplog.records)


def test_tlp_empty_refs_returns_none() -> None:
    from app.ingest.taxii_parser import resolve_tlp_marking
    assert resolve_tlp_marking([], TLP_CACHE) is None
    assert resolve_tlp_marking(None, TLP_CACHE) is None


def test_normalise_indicator_shape() -> None:
    from app.ingest.dedup import taxii_content_hash
    from app.ingest.taxii_parser import normalise_stix_object
    indicator = _fixture_objects()[0]
    row = normalise_stix_object(indicator, SRC_ID, TLP_CACHE)
    assert row is not None
    assert row["stix_type"] == "indicator"
    assert row["stix_id"] == "indicator--a932fcc6-e032-476c-826f-cb970a5a1ade"
    assert row["tlp_marking_id"] == TLP_AMBER
    assert row["source_id"] == SRC_ID
    assert row["content_hash"] == taxii_content_hash(
        str(SRC_ID), indicator["id"], indicator["modified"]
    )
    assert row["observed_at"] == datetime(2026, 4, 7, 12, 0, 0, tzinfo=timezone.utc)
    assert row["visibility"] == "shared"


def test_normalise_preserves_raw_stix() -> None:
    from app.ingest.taxii_parser import normalise_stix_object
    indicator = _fixture_objects()[0]
    row = normalise_stix_object(indicator, SRC_ID, TLP_CACHE)
    assert row is not None
    raw = row["raw_stix"]
    assert isinstance(raw, dict)
    # Round-trippable JSON
    json.dumps(raw)
    assert raw["id"] == indicator["id"]
    assert raw["type"] == "indicator"


def test_normalise_custom_type_prefixed() -> None:
    from app.ingest.taxii_parser import normalise_stix_object
    custom = {
        "type": "x-misp-attribute",
        "id": "x-misp-attribute--11111111-1111-1111-1111-111111111111",
        "spec_version": "2.1",
        "created": "2026-01-01T00:00:00.000Z",
        "modified": "2026-01-01T00:00:00.000Z",
    }
    row = normalise_stix_object(custom, SRC_ID, TLP_CACHE)
    assert row is not None
    assert row["stix_type"] == "x-custom-x-misp-attribute"


def test_normalise_indicator_title_from_name() -> None:
    from app.ingest.taxii_parser import normalise_stix_object
    indicator = _fixture_objects()[0]
    row = normalise_stix_object(indicator, SRC_ID, TLP_CACHE)
    assert row["title"] == "Fixture malicious domain"


def test_normalise_indicator_without_name_uses_pattern_prefix() -> None:
    from app.ingest.taxii_parser import normalise_stix_object
    ind = {
        "type": "indicator",
        "id": "indicator--33333333-3333-3333-3333-333333333333",
        "spec_version": "2.1",
        "created": "2026-03-01T00:00:00.000Z",
        "modified": "2026-03-01T00:00:00.000Z",
        "pattern": "[domain-name:value = 'x.example']" * 20,
        "pattern_type": "stix",
        "valid_from": "2026-03-01T00:00:00.000Z",
        "labels": ["malicious-activity"],
    }
    row = normalise_stix_object(ind, SRC_ID, TLP_CACHE)
    assert row is not None
    assert row["title"] is not None
    assert len(row["title"]) <= 120


def test_normalise_drops_object_missing_id(caplog: pytest.LogCaptureFixture) -> None:
    from app.ingest.taxii_parser import normalise_stix_object
    obj = {"type": "indicator", "modified": "2026-01-01T00:00:00.000Z",
           "created": "2026-01-01T00:00:00.000Z"}
    with caplog.at_level("WARNING"):
        row = normalise_stix_object(obj, SRC_ID, TLP_CACHE)
    assert row is None
    assert any("feed_item_rejected" in rec.getMessage() for rec in caplog.records)


def test_normalise_drops_object_missing_modified() -> None:
    from app.ingest.taxii_parser import normalise_stix_object
    obj = {"type": "indicator", "id": "indicator--44444444-4444-4444-4444-444444444444"}
    row = normalise_stix_object(obj, SRC_ID, TLP_CACHE)
    assert row is None


def test_normalise_attack_pattern_fixture() -> None:
    from app.ingest.taxii_parser import normalise_stix_object
    ap = _fixture_objects()[1]
    row = normalise_stix_object(ap, SRC_ID, TLP_CACHE)
    assert row is not None
    assert row["stix_type"] == "attack-pattern"
    assert row["tlp_marking_id"] == TLP_GREEN


# ──────────────────── Worker-level (Task 2) ────────────────────


@contextmanager
def _fake_session_ctx_taxii(*_a, **_kw):
    s = MagicMock()
    s.__enter__ = lambda self: self
    s.__exit__ = lambda self, *a: None
    yield s


class _FakeCollection:
    """Reusable test stand-in for a taxii2client Collection."""
    def __init__(self, pages: list[dict]):
        self.pages = list(pages)
        self.calls: list[dict] = []
        self.id = "fake-collection"

    def get_objects(self, **kwargs):
        self.calls.append(kwargs)
        if not self.pages:
            return {"objects": [], "more": False}
        return self.pages.pop(0)


class _FakeApiRoot:
    def __init__(self, collections: list[_FakeCollection]):
        self.collections = collections


class _FakeServer:
    def __init__(self, api_roots: list[_FakeApiRoot]):
        self.api_roots = api_roots


TLP_CACHE_MATCH = {TLP_CLEAR: "TLP:CLEAR", TLP_GREEN: "TLP:GREEN",
                  TLP_AMBER: "TLP:AMBER", TLP_RED: "TLP:RED"}


def _install_taxii_mocks(monkeypatch: pytest.MonkeyPatch, *, server: Any,
                         source_row: dict):
    from app.workers import taxii as taxii_module
    calls: dict = {"persist": [], "health": [], "cursor": None}

    monkeypatch.setattr(taxii_module, "_fetch_source_row", lambda s, sid: source_row)
    monkeypatch.setattr(taxii_module, "_open_session", _fake_session_ctx_taxii)
    monkeypatch.setattr(taxii_module, "_load_tlp_cache", lambda s: TLP_CACHE_MATCH)
    monkeypatch.setattr(taxii_module, "_build_server", lambda *a, **kw: server)

    def fake_persist(session, row):
        calls["persist"].append(row["stix_id"])
        return 1
    monkeypatch.setattr(taxii_module, "_persist_event", fake_persist)

    def fake_health(session, sid, *, status, succeeded):
        calls["health"].append((status, succeeded))
    monkeypatch.setattr(taxii_module, "update_source_health", fake_health)

    def fake_advance_cursor(session, sid, cursor_str):
        calls["cursor"] = cursor_str
    monkeypatch.setattr(taxii_module, "_advance_cursor", fake_advance_cursor)

    return calls


def test_poll_taxii_actor_registered() -> None:
    import dramatiq
    from app.workers import taxii as taxii_module
    assert isinstance(taxii_module.poll_taxii, dramatiq.Actor)


def test_poll_taxii_first_poll_has_no_added_after(monkeypatch: pytest.MonkeyPatch):
    from app.workers import taxii as taxii_module
    coll = _FakeCollection(pages=[{"objects": [], "more": False}])
    server = _FakeServer([_FakeApiRoot([coll])])
    sid = uuid.uuid4()
    calls = _install_taxii_mocks(monkeypatch, server=server,
                                 source_row={"id": sid, "url": "http://x",
                                             "credentials_enc": None,
                                             "last_cursor": None})
    taxii_module.poll_taxii_impl(str(sid))
    assert coll.calls
    assert coll.calls[0].get("added_after") is None


def test_poll_taxii_subsequent_poll_uses_cursor(monkeypatch: pytest.MonkeyPatch):
    from app.workers import taxii as taxii_module
    coll = _FakeCollection(pages=[{"objects": [], "more": False}])
    server = _FakeServer([_FakeApiRoot([coll])])
    sid = uuid.uuid4()
    _install_taxii_mocks(monkeypatch, server=server, source_row={
        "id": sid, "url": "http://x", "credentials_enc": None,
        "last_cursor": "2026-04-07T12:00:00+00:00",
    })
    taxii_module.poll_taxii_impl(str(sid))
    assert coll.calls[0]["added_after"] == "2026-04-07T12:00:00+00:00"


def test_poll_taxii_loops_pagination(monkeypatch: pytest.MonkeyPatch):
    from app.workers import taxii as taxii_module
    page1_obj = _fixture_objects()[0]  # indicator
    page2_obj = _fixture_objects()[1]  # attack-pattern
    coll = _FakeCollection(pages=[
        {"objects": [page1_obj], "more": True, "next": "cursor2"},
        {"objects": [page2_obj], "more": False},
    ])
    server = _FakeServer([_FakeApiRoot([coll])])
    sid = uuid.uuid4()
    calls = _install_taxii_mocks(monkeypatch, server=server, source_row={
        "id": sid, "url": "http://x", "credentials_enc": None, "last_cursor": None,
    })
    taxii_module.poll_taxii_impl(str(sid))
    assert len(coll.calls) == 2
    assert coll.calls[1].get("next") == "cursor2"
    assert set(calls["persist"]) == {page1_obj["id"], page2_obj["id"]}


def test_poll_taxii_cursor_advanced_after_all_pages(monkeypatch: pytest.MonkeyPatch):
    """Cursor advance MUST happen after all persist calls —."""
    from app.workers import taxii as taxii_module
    page1_obj = _fixture_objects()[0]
    page2_obj = _fixture_objects()[1]
    coll = _FakeCollection(pages=[
        {"objects": [page1_obj], "more": True, "next": "cursor2"},
        {"objects": [page2_obj], "more": False},
    ])
    server = _FakeServer([_FakeApiRoot([coll])])
    sid = uuid.uuid4()

    # Order-tracking version of the mocks
    call_log: list[str] = []
    monkeypatch.setattr(taxii_module, "_fetch_source_row", lambda s, sid: {
        "id": sid, "url": "http://x", "credentials_enc": None, "last_cursor": None,
    })
    monkeypatch.setattr(taxii_module, "_open_session", _fake_session_ctx_taxii)
    monkeypatch.setattr(taxii_module, "_load_tlp_cache", lambda s: TLP_CACHE_MATCH)
    monkeypatch.setattr(taxii_module, "_build_server", lambda *a, **kw: server)

    def fake_persist(session, row):
        call_log.append("persist")
        return 1
    monkeypatch.setattr(taxii_module, "_persist_event", fake_persist)
    monkeypatch.setattr(taxii_module, "update_source_health",
                        lambda s, sid, *, status, succeeded: call_log.append("health"))
    monkeypatch.setattr(taxii_module, "_advance_cursor",
                        lambda *a, **kw: call_log.append("cursor_advance"))

    taxii_module.poll_taxii_impl(str(sid))
    # Must persist both objects BEFORE cursor advance
    first_persist = call_log.index("persist")
    last_persist = len(call_log) - 1 - list(reversed(call_log)).index("persist")
    cursor_idx = call_log.index("cursor_advance")
    assert cursor_idx > last_persist


def test_poll_taxii_cursor_not_advanced_on_page_error(monkeypatch: pytest.MonkeyPatch):
    from app.workers import taxii as taxii_module
    page1_obj = _fixture_objects()[0]

    class _BrokenCollection(_FakeCollection):
        def get_objects(self, **kwargs):
            if not self.calls:
                self.calls.append(kwargs)
                return {"objects": [page1_obj], "more": True, "next": "cursor2"}
            raise OSError("connection dropped")

    coll = _BrokenCollection(pages=[])
    server = _FakeServer([_FakeApiRoot([coll])])
    sid = uuid.uuid4()
    calls = _install_taxii_mocks(monkeypatch, server=server, source_row={
        "id": sid, "url": "http://x", "credentials_enc": None, "last_cursor": None,
    })
    taxii_module.poll_taxii_impl(str(sid))
    assert calls["cursor"] is None
    assert calls["health"] == [("network_error", False)]


def test_poll_taxii_resolves_tlp_from_fixture(monkeypatch: pytest.MonkeyPatch):
    from app.workers import taxii as taxii_module
    coll = _FakeCollection(pages=[
        {"objects": _fixture_objects(), "more": False},
    ])
    server = _FakeServer([_FakeApiRoot([coll])])
    sid = uuid.uuid4()

    persisted_rows: list[dict] = []
    monkeypatch.setattr(taxii_module, "_fetch_source_row", lambda s, sid: {
        "id": sid, "url": "http://x", "credentials_enc": None, "last_cursor": None,
    })
    monkeypatch.setattr(taxii_module, "_open_session", _fake_session_ctx_taxii)
    monkeypatch.setattr(taxii_module, "_load_tlp_cache", lambda s: TLP_CACHE_MATCH)
    monkeypatch.setattr(taxii_module, "_build_server", lambda *a, **kw: server)
    monkeypatch.setattr(taxii_module, "_persist_event",
                        lambda s, row: (persisted_rows.append(row), 1)[1])
    monkeypatch.setattr(taxii_module, "update_source_health", lambda *a, **kw: None)
    monkeypatch.setattr(taxii_module, "_advance_cursor", lambda *a, **kw: None)

    taxii_module.poll_taxii_impl(str(sid))
    by_type = {r["stix_type"]: r for r in persisted_rows}
    assert by_type["indicator"]["tlp_marking_id"] == TLP_AMBER
    assert by_type["attack-pattern"]["tlp_marking_id"] == TLP_GREEN


def test_poll_taxii_loads_tlp_cache_from_db(monkeypatch: pytest.MonkeyPatch):
    from app.workers import taxii as taxii_module
    coll = _FakeCollection(pages=[{"objects": [], "more": False}])
    server = _FakeServer([_FakeApiRoot([coll])])
    calls: list[str] = []
    monkeypatch.setattr(taxii_module, "_fetch_source_row", lambda s, sid: {
        "id": sid, "url": "http://x", "credentials_enc": None, "last_cursor": None,
    })
    monkeypatch.setattr(taxii_module, "_open_session", _fake_session_ctx_taxii)
    monkeypatch.setattr(taxii_module, "_load_tlp_cache",
                        lambda s: (calls.append("loaded"), TLP_CACHE_MATCH)[1])
    monkeypatch.setattr(taxii_module, "_build_server", lambda *a, **kw: server)
    monkeypatch.setattr(taxii_module, "update_source_health", lambda *a, **kw: None)
    monkeypatch.setattr(taxii_module, "_advance_cursor", lambda *a, **kw: None)
    monkeypatch.setattr(taxii_module, "_persist_event", lambda *a, **kw: 1)

    taxii_module.poll_taxii_impl(str(uuid.uuid4()))
    assert calls == ["loaded"]


def test_poll_taxii_version_negotiation_fallback(monkeypatch: pytest.MonkeyPatch):
    from app.workers import taxii as taxii_module
    attempts: list[str] = []
    class _BadV21:
        def __init__(self, *a, **kw):
            attempts.append("v21")
            raise OSError("404")
    class _OkV20:
        def __init__(self, *a, **kw):
            attempts.append("v20")
            self.api_roots = []
    monkeypatch.setattr(taxii_module, "taxii_v21_Server", _BadV21)
    monkeypatch.setattr(taxii_module, "taxii_v20_Server", _OkV20)
    sid = uuid.uuid4()
    monkeypatch.setattr(taxii_module, "_fetch_source_row", lambda s, sid: {
        "id": sid, "url": "http://x", "credentials_enc": None, "last_cursor": None,
    })
    monkeypatch.setattr(taxii_module, "_open_session", _fake_session_ctx_taxii)
    monkeypatch.setattr(taxii_module, "_load_tlp_cache", lambda s: TLP_CACHE_MATCH)
    health: list = []
    monkeypatch.setattr(taxii_module, "update_source_health",
                        lambda s, sid, *, status, succeeded: health.append((status, succeeded)))
    monkeypatch.setattr(taxii_module, "_advance_cursor", lambda *a, **kw: None)
    taxii_module.poll_taxii_impl(str(sid))
    assert attempts == ["v21", "v20"]


_TEST_SECRET = "a" * 32 + "deadbeef"  # >= 32 chars, passes Settings validator


def test_poll_taxii_decrypts_basic_auth(monkeypatch: pytest.MonkeyPatch):
    from app.crypto import encrypt_credentials
    from app.workers import taxii as taxii_module

    # Patch settings.SECRET_KEY so decrypt_credentials uses the same key.
    # Must patch the attribute directly (not via env) because app.config.settings
    # is a module-level singleton and may already be loaded by the time this test
    # runs (e.g. after importing app.routers.admin.sources in another test).
    monkeypatch.setenv("SECRET_KEY", _TEST_SECRET)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    import app.config as _cfg
    monkeypatch.setattr(_cfg.settings, "SECRET_KEY", _TEST_SECRET)

    captured: dict = {}
    def _mk_server(url, creds):
        captured["url"] = url
        captured["creds"] = creds
        return _FakeServer([_FakeApiRoot([_FakeCollection(pages=[{"objects": [], "more": False}])])])
    monkeypatch.setattr(taxii_module, "_build_server", _mk_server)

    sid = uuid.uuid4()
    blob = encrypt_credentials(_TEST_SECRET,
                               {"type": "basic", "username": "u", "password": "p"})
    monkeypatch.setattr(taxii_module, "_fetch_source_row", lambda s, sid: {
        "id": sid, "url": "http://x", "credentials_enc": blob, "last_cursor": None,
    })
    monkeypatch.setattr(taxii_module, "_open_session", _fake_session_ctx_taxii)
    monkeypatch.setattr(taxii_module, "_load_tlp_cache", lambda s: TLP_CACHE_MATCH)
    monkeypatch.setattr(taxii_module, "update_source_health", lambda *a, **kw: None)
    monkeypatch.setattr(taxii_module, "_advance_cursor", lambda *a, **kw: None)
    monkeypatch.setattr(taxii_module, "_persist_event", lambda *a, **kw: 1)

    taxii_module.poll_taxii_impl(str(sid))
    assert captured["creds"] == {"type": "basic", "username": "u", "password": "p"}


def test_poll_taxii_unauthenticated_no_credentials(monkeypatch: pytest.MonkeyPatch):
    from app.workers import taxii as taxii_module
    captured: dict = {}
    def _mk_server(url, creds):
        captured["creds"] = creds
        return _FakeServer([_FakeApiRoot([_FakeCollection(pages=[{"objects": [], "more": False}])])])
    monkeypatch.setattr(taxii_module, "_build_server", _mk_server)

    sid = uuid.uuid4()
    monkeypatch.setattr(taxii_module, "_fetch_source_row", lambda s, sid: {
        "id": sid, "url": "http://x", "credentials_enc": None, "last_cursor": None,
    })
    monkeypatch.setattr(taxii_module, "_open_session", _fake_session_ctx_taxii)
    monkeypatch.setattr(taxii_module, "_load_tlp_cache", lambda s: TLP_CACHE_MATCH)
    monkeypatch.setattr(taxii_module, "update_source_health", lambda *a, **kw: None)
    monkeypatch.setattr(taxii_module, "_advance_cursor", lambda *a, **kw: None)
    monkeypatch.setattr(taxii_module, "_persist_event", lambda *a, **kw: 1)
    taxii_module.poll_taxii_impl(str(sid))
    assert captured["creds"] is None
