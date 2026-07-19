"""RSS parser + normaliser + worker tests - INGR-01, INGR-02, INGR-03.

Parser-level (Task 1 of-03): pure functions over feedparser output
using the backend/tests/fixtures/rss_krebs_2026-04.xml golden file.
Worker-level (Task 2): mocks the DB session and asserts _persist_event
+ update_source_health call shapes.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "rss_krebs_2026-04.xml"
SRC_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@contextmanager
def _fake_session_ctx(*_args, **_kwargs):
    """Context manager returning a MagicMock session with commit/rollback no-ops."""
    from unittest.mock import MagicMock
    s = MagicMock()
    s.__enter__ = lambda self: self
    s.__exit__ = lambda self, *a: None
    yield s


# ──────────────────────────────────────── Parser-level (Task 1) ────

def test_parse_fixture_returns_two_entries() -> None:
    from app.ingest.rss_parser import parse_rss_feed
    parsed = parse_rss_feed(str(FIXTURE))
    assert len(parsed.entries) == 2


def test_normalise_first_entry_shape() -> None:
    from app.ingest.rss_parser import normalise_rss_entry, parse_rss_feed
    parsed = parse_rss_feed(str(FIXTURE))
    row = normalise_rss_entry(parsed.entries[0], SRC_ID)
    assert row is not None
    assert row["stix_type"] == "x-intellibird-rss"
    assert row["source_id"] == SRC_ID
    assert row["title"] == "Fixture Entry One - Supply Chain Compromise"
    assert row["raw_reference"] == "https://krebsonsecurity.com/2026/04/fixture-one/"
    assert row["visibility"] == "shared"
    import re
    assert re.match(r"^[0-9a-f]{64}$", row["content_hash"])
    assert isinstance(row["observed_at"], datetime)
    assert row["observed_at"].tzinfo is not None


def test_observed_at_from_pubdate() -> None:
    from app.ingest.rss_parser import normalise_rss_entry, parse_rss_feed
    parsed = parse_rss_feed(str(FIXTURE))
    row = normalise_rss_entry(parsed.entries[0], SRC_ID)
    assert row is not None
    expected = datetime(2026, 4, 7, 14, 0, 0, tzinfo=timezone.utc)
    assert row["observed_at"] == expected


def test_content_hash_matches_helper() -> None:
    from app.ingest.dedup import rss_content_hash
    from app.ingest.rss_parser import normalise_rss_entry, parse_rss_feed
    parsed = parse_rss_feed(str(FIXTURE))
    for entry in parsed.entries:
        row = normalise_rss_entry(entry, SRC_ID)
        assert row is not None
        assert row["content_hash"] == rss_content_hash(
            str(SRC_ID), entry.link, entry.title
        )


def test_normalise_drops_entry_without_link_or_title() -> None:
    from app.ingest.rss_parser import normalise_rss_entry
    empty = {"title": "", "link": "", "id": ""}
    assert normalise_rss_entry(empty, SRC_ID) is None


def test_normalise_title_only_entry_dropped() -> None:
    from app.ingest.rss_parser import normalise_rss_entry
    # Title present, but no link and no id → unhashable
    orphan = {"title": "lonely headline", "link": "", "id": ""}
    assert normalise_rss_entry(orphan, SRC_ID) is None


def test_normalise_falls_back_to_updated_parsed() -> None:
    from app.ingest.rss_parser import normalise_rss_entry
    import time
    # 2026-04-10T09:00:00Z as struct_time
    st = time.strptime("2026-04-10 09:00:00 +0000", "%Y-%m-%d %H:%M:%S %z")
    entry = {
        "title": "t", "link": "https://ex/x", "id": "https://ex/x",
        "updated_parsed": st,
    }
    row = normalise_rss_entry(entry, SRC_ID)
    assert row is not None
    assert row["observed_at"].year == 2026
    assert row["observed_at"].month == 4
    assert row["observed_at"].day == 10


def test_normalise_falls_back_to_now_when_no_timestamp() -> None:
    from app.ingest.rss_parser import normalise_rss_entry
    entry = {"title": "t", "link": "https://ex/y", "id": "https://ex/y"}
    row = normalise_rss_entry(entry, SRC_ID)
    assert row is not None
    now = datetime.now(timezone.utc)
    assert abs((now - row["observed_at"]).total_seconds()) < 5


def test_title_truncation_to_2048() -> None:
    from app.ingest.rss_parser import normalise_rss_entry
    entry = {"title": "x" * 10_000, "link": "https://ex/z", "id": "https://ex/z"}
    row = normalise_rss_entry(entry, SRC_ID)
    assert row is not None
    assert len(row["title"]) == 2048


def test_link_id_fallback() -> None:
    from app.ingest.dedup import rss_content_hash
    from app.ingest.rss_parser import normalise_rss_entry
    entry = {"title": "no link but has id", "link": "", "id": "urn:guid-abc"}
    row = normalise_rss_entry(entry, SRC_ID)
    assert row is not None
    assert row["raw_reference"] == "urn:guid-abc"
    assert row["content_hash"] == rss_content_hash(str(SRC_ID), "urn:guid-abc", "no link but has id")


# ──────────────────────────────────────── Worker-level (Task 2) ────

class _FakeEntry(dict):
    """Tests use plain dict entries - feedparser.FeedParserDict duck-types via.get/.attr."""
    def __getattr__(self, k: str):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e


def _mock_parsed(entries: list[dict]) -> Any:  # noqa: ANN401
    """Build a minimal FeedParserDict-ish stand-in."""
    from types import SimpleNamespace
    return SimpleNamespace(entries=[_FakeEntry(**e) for e in entries], bozo=0, status=200)


def test_poll_rss_actor_registered() -> None:
    import dramatiq
    from app.workers import rss as rss_module
    assert isinstance(rss_module.poll_rss, dramatiq.Actor)


def test_poll_rss_fetches_and_normalises(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import rss as rss_module

    sid = uuid.uuid4()
    entries = [
        {"title": "a", "link": "https://ex/a", "id": "https://ex/a"},
        {"title": "b", "link": "https://ex/b", "id": "https://ex/b"},
    ]
    monkeypatch.setattr(rss_module, "parse_rss_feed", lambda *a, **kw: _mock_parsed(entries))

    calls: dict = {"persist": 0, "health": []}
    def fake_persist(session, row):
        calls["persist"] += 1
        return 1
    def fake_health(session, source_id, *, status, succeeded):
        calls["health"].append((status, succeeded))

    monkeypatch.setattr(rss_module, "_persist_event", fake_persist)
    monkeypatch.setattr(rss_module, "update_source_health", fake_health)
    monkeypatch.setattr(rss_module, "_fetch_source_row", lambda s, sid: {
        "id": sid, "url": "http://fixture", "credentials_enc": None,
    })
    monkeypatch.setattr(rss_module, "_open_session", _fake_session_ctx)

    rss_module.poll_rss_impl(str(sid))
    assert calls["persist"] == 2
    assert calls["health"] == [("ok", True)]


def test_poll_rss_handles_parse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import rss as rss_module
    from types import SimpleNamespace
    monkeypatch.setattr(rss_module, "parse_rss_feed",
                        lambda *a, **kw: SimpleNamespace(entries=[], bozo=1, status=200,
                                                         bozo_exception=ValueError("malformed xml")))
    health: list = []
    monkeypatch.setattr(rss_module, "update_source_health",
                        lambda s, sid, *, status, succeeded: health.append((status, succeeded)))
    monkeypatch.setattr(rss_module, "_fetch_source_row", lambda s, sid: {
        "id": sid, "url": "http://fixture", "credentials_enc": None,
    })
    monkeypatch.setattr(rss_module, "_open_session", _fake_session_ctx)
    monkeypatch.setattr(rss_module, "_persist_event", lambda *a, **kw: 0)

    rss_module.poll_rss_impl(str(uuid.uuid4()))
    assert health == [("parse_error", False)]


def test_poll_rss_handles_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import rss as rss_module

    def boom(*a, **kw):
        raise OSError("connection refused")
    monkeypatch.setattr(rss_module, "parse_rss_feed", boom)
    health: list = []
    monkeypatch.setattr(rss_module, "update_source_health",
                        lambda s, sid, *, status, succeeded: health.append((status, succeeded)))
    monkeypatch.setattr(rss_module, "_fetch_source_row", lambda s, sid: {
        "id": sid, "url": "http://fixture", "credentials_enc": None,
    })
    monkeypatch.setattr(rss_module, "_open_session", _fake_session_ctx)
    monkeypatch.setattr(rss_module, "_persist_event", lambda *a, **kw: 0)

    rss_module.poll_rss_impl(str(uuid.uuid4()))
    assert health == [("network_error", False)]


def test_poll_rss_drops_unhashable_entry_with_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.workers import rss as rss_module
    entries = [
        {"title": "valid", "link": "https://ex/ok", "id": "https://ex/ok"},
        {"title": "", "link": "", "id": ""},  # unhashable
    ]
    monkeypatch.setattr(rss_module, "parse_rss_feed", lambda *a, **kw: _mock_parsed(entries))
    persist_calls: list[int] = []
    monkeypatch.setattr(rss_module, "_persist_event",
                        lambda s, row: persist_calls.append(1) or 1)
    monkeypatch.setattr(rss_module, "update_source_health",
                        lambda *a, **kw: None)
    monkeypatch.setattr(rss_module, "_fetch_source_row", lambda s, sid: {
        "id": sid, "url": "http://fixture", "credentials_enc": None,
    })
    monkeypatch.setattr(rss_module, "_open_session", _fake_session_ctx)

    with caplog.at_level("WARNING"):
        rss_module.poll_rss_impl(str(uuid.uuid4()))
    assert len(persist_calls) == 1
    assert any("feed_item_rejected" in rec.getMessage() or
               "feed_item_rejected" in str(getattr(rec, 'event', ''))
               for rec in caplog.records)
