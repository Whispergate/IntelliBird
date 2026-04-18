"""NVD parser + worker tests — INGC-01, INGC-02, INGC-03.

Parser-level (Task 1): pure normalise_cve + extract_attack_techniques
against the captured nvd_cve_sample.json golden fixture.
Worker-level (Task 2): mocks nvdlib.searchCVE_V2 and asserts 30d
backfill, cursor advance, 429 backoff, INGC-03 tag writes.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "nvd_cve_sample.json"
SRC_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _ns(d: Any) -> Any:
    """Recursively convert dict/list → SimpleNamespace for attribute access."""
    if isinstance(d, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in d.items()})
    if isinstance(d, list):
        return [_ns(x) for x in d]
    return d


def _fake_cve_from_fixture() -> Any:
    raw = json.loads(FIXTURE.read_text())
    cve_json = raw["vulnerabilities"][0]["cve"]
    return _ns(cve_json)


# ───────────────────────── Parser-level (Task 1) ─────────────────────────

def test_normalise_cve_event_shape() -> None:
    from app.ingest.dedup import nvd_content_hash
    from app.ingest.nvd_parser import normalise_cve
    cve = _fake_cve_from_fixture()
    result = normalise_cve(cve, SRC_ID)
    assert result is not None
    event_row, cve_details_row, attack_links = result

    assert event_row["stix_type"] == "x-nvd-cve"
    assert event_row["source_id"] == SRC_ID
    assert event_row["raw_reference"] == "CVE-2024-99999"
    assert event_row["title"] == "CVE-2024-99999"
    assert event_row["description"].startswith("Fixture CVE")
    assert event_row["content_hash"] == nvd_content_hash(
        str(SRC_ID), "CVE-2024-99999", "2026-04-10T12:00:00.000"
    )
    assert event_row["visibility"] == "shared"
    assert event_row["observed_at"].year == 2026
    assert event_row["observed_at"].tzinfo is not None


def test_normalise_cve_cve_details_shape() -> None:
    from app.ingest.nvd_parser import normalise_cve
    cve = _fake_cve_from_fixture()
    _, cvd, _ = normalise_cve(cve, SRC_ID)
    assert cvd["cve_id"] == "CVE-2024-99999"
    assert cvd["cvss_v3_score"] == 9.8
    assert cvd["cvss_v3_vector"] == "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
    assert isinstance(cvd["cpe_match"], list) and len(cvd["cpe_match"]) == 1
    assert cvd["cpe_match"][0]["criteria"].startswith("cpe:2.3:a:fixture")
    assert cvd["cwe_ids"] == ["CWE-89"]
    assert cvd["last_modified"] == datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc)


def test_extract_attack_techniques_url_match() -> None:
    from app.ingest.nvd_parser import extract_attack_techniques
    cve = _fake_cve_from_fixture()
    techs = extract_attack_techniques(cve)
    assert techs == [("T1190", "https://attack.mitre.org/techniques/T1190/")]


def test_extract_attack_techniques_no_match() -> None:
    from app.ingest.nvd_parser import extract_attack_techniques
    cve = _ns({"references": [{"url": "https://example.com/x", "tags": ["Vendor Advisory"]}]})
    assert extract_attack_techniques(cve) == []


def test_extract_attack_techniques_tag_match() -> None:
    from app.ingest.nvd_parser import extract_attack_techniques
    cve = _ns({"references": [{
        "url": "https://ex/adv",
        "tags": ["Exploit", "T1059.003"],
    }]})
    result = extract_attack_techniques(cve)
    assert result == [("T1059.003", "https://ex/adv")]


def test_extract_attack_techniques_tag_without_exploit_rejected() -> None:
    from app.ingest.nvd_parser import extract_attack_techniques
    cve = _ns({"references": [{
        "url": "https://ex/adv",
        "tags": ["T1059", "Third Party Advisory"],  # no Exploit/VDB Entry
    }]})
    assert extract_attack_techniques(cve) == []


def test_extract_attack_techniques_subtechnique() -> None:
    from app.ingest.nvd_parser import extract_attack_techniques
    cve = _ns({"references": [{
        "url": "https://attack.mitre.org/techniques/T1059.001/",
        "tags": [],
    }]})
    assert extract_attack_techniques(cve) == [
        ("T1059.001", "https://attack.mitre.org/techniques/T1059.001/")
    ]


def test_cve_missing_lastmodified_returns_none() -> None:
    from app.ingest.nvd_parser import normalise_cve
    cve = _ns({"id": "CVE-2024-X", "descriptions": [], "references": []})
    assert normalise_cve(cve, SRC_ID) is None


def test_cve_missing_cve_id_returns_none() -> None:
    from app.ingest.nvd_parser import normalise_cve
    cve = _ns({"lastModified": "2026-01-01T00:00:00.000", "descriptions": [], "references": []})
    assert normalise_cve(cve, SRC_ID) is None


def test_cve_without_cvss_v3_metric() -> None:
    from app.ingest.nvd_parser import normalise_cve
    cve = _ns({
        "id": "CVE-2024-Z",
        "lastModified": "2026-01-02T00:00:00.000",
        "published": "2026-01-02T00:00:00.000",
        "descriptions": [{"lang": "en", "value": "no cvss v3"}],
        "metrics": SimpleNamespace(),
        "weaknesses": [],
        "configurations": [],
        "references": [],
    })
    _, cvd, _ = normalise_cve(cve, SRC_ID)
    assert cvd["cvss_v3_score"] is None
    assert cvd["cvss_v3_vector"] is None


def test_cve_without_cpe_match() -> None:
    from app.ingest.nvd_parser import normalise_cve
    cve = _ns({
        "id": "CVE-2024-Y",
        "lastModified": "2026-01-03T00:00:00.000",
        "published": "2026-01-03T00:00:00.000",
        "descriptions": [{"lang": "en", "value": "no cpe"}],
        "metrics": SimpleNamespace(),
        "weaknesses": [],
        "configurations": [],
        "references": [],
    })
    _, cvd, _ = normalise_cve(cve, SRC_ID)
    assert not cvd["cpe_match"]  # None or [] both acceptable


def test_cve_hash_matches_helper() -> None:
    from app.ingest.dedup import nvd_content_hash
    from app.ingest.nvd_parser import normalise_cve
    cve = _fake_cve_from_fixture()
    event_row, _, _ = normalise_cve(cve, SRC_ID)
    assert event_row["content_hash"] == nvd_content_hash(
        str(SRC_ID), "CVE-2024-99999", "2026-04-10T12:00:00.000"
    )


# ──────────────────────────── Worker-level (Task 2) ────────────────────────────

from contextlib import contextmanager
from unittest.mock import MagicMock


@contextmanager
def _fake_session_ctx_nvd(*_args, **_kwargs):
    s = MagicMock()
    s.__enter__ = lambda self: self
    s.__exit__ = lambda self, *a: None
    yield s


class _NvdError(Exception):
    """Stand-in for nvdlib exception hierarchy — tests set .status_code."""
    def __init__(self, msg: str, status_code: int) -> None:
        super().__init__(msg)
        self.status_code = status_code


def test_poll_nvd_actor_registered() -> None:
    import dramatiq
    from app.workers import nvd as nvd_module
    assert isinstance(nvd_module.poll_nvd, dramatiq.Actor)


def _install_common_mocks(monkeypatch: pytest.MonkeyPatch, cves: list[Any],
                          source_row: dict) -> dict:
    from app.workers import nvd as nvd_module
    calls: dict = {"search_kwargs": [], "health": [], "cursor": None, "events": 0,
                   "cve_details": 0, "attack_tags": []}

    def fake_search(**kwargs):
        calls["search_kwargs"].append(kwargs)
        for c in cves:
            yield c

    monkeypatch.setattr(nvd_module.nvdlib, "searchCVE_V2", fake_search)
    monkeypatch.setattr(nvd_module, "_fetch_source_row", lambda s, sid: source_row)
    monkeypatch.setattr(nvd_module, "_open_session", _fake_session_ctx_nvd)

    def fake_persist(session, row):
        calls["events"] += 1
        row["_assigned_id"] = uuid.uuid4()
        return 1
    monkeypatch.setattr(nvd_module, "_persist_event", fake_persist)

    def fake_write_cve_details(session, event_id, row):
        calls["cve_details"] += 1
    monkeypatch.setattr(nvd_module, "_write_cve_details", fake_write_cve_details)

    def fake_write_attack_tag(session, event_id, technique_id, url):
        calls["attack_tags"].append((technique_id, url))
    monkeypatch.setattr(nvd_module, "_write_attack_tag", fake_write_attack_tag)

    def fake_health(session, sid, *, status, succeeded):
        calls["health"].append((status, succeeded))
    monkeypatch.setattr(nvd_module, "update_source_health", fake_health)

    def fake_advance_cursor(session, sid, cursor_str):
        calls["cursor"] = cursor_str
    monkeypatch.setattr(nvd_module, "_advance_cursor", fake_advance_cursor)

    return calls


def test_poll_nvd_first_poll_uses_30d_backfill(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import timedelta
    from app.workers import nvd as nvd_module
    sid = uuid.uuid4()
    source = {"id": sid, "credentials_enc": None, "last_cursor": None}
    calls = _install_common_mocks(monkeypatch, [], source)

    nvd_module.poll_nvd_impl(str(sid))

    kwargs = calls["search_kwargs"][0]
    start = kwargs["lastModStartDate"]
    if isinstance(start, str):
        start = datetime.fromisoformat(start.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    gap = now - start
    assert timedelta(days=29, hours=23) < gap < timedelta(days=30, hours=1)


def test_poll_nvd_subsequent_uses_cursor_plus_one_second(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import nvd as nvd_module
    sid = uuid.uuid4()
    source = {"id": sid, "credentials_enc": None,
              "last_cursor": "2026-04-10T12:00:00+00:00"}
    calls = _install_common_mocks(monkeypatch, [], source)

    nvd_module.poll_nvd_impl(str(sid))
    start = calls["search_kwargs"][0]["lastModStartDate"]
    if isinstance(start, str):
        start = datetime.fromisoformat(start.replace("Z", "+00:00"))
    assert start == datetime(2026, 4, 10, 12, 0, 1, tzinfo=timezone.utc)


def test_poll_nvd_advances_cursor_to_latest_plus_one_second(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workers import nvd as nvd_module
    sid = uuid.uuid4()
    source = {"id": sid, "credentials_enc": None,
              "last_cursor": "2026-04-10T10:00:00+00:00"}

    cve_a = _ns({
        "id": "CVE-A", "lastModified": "2026-04-10T12:00:00.000",
        "published": "2026-04-10T12:00:00.000",
        "descriptions": [], "metrics": SimpleNamespace(),
        "weaknesses": [], "configurations": [], "references": [],
    })
    cve_b = _ns({
        "id": "CVE-B", "lastModified": "2026-04-10T12:05:00.000",
        "published": "2026-04-10T12:05:00.000",
        "descriptions": [], "metrics": SimpleNamespace(),
        "weaknesses": [], "configurations": [], "references": [],
    })
    calls = _install_common_mocks(monkeypatch, [cve_a, cve_b], source)

    nvd_module.poll_nvd_impl(str(sid))
    assert calls["cursor"] == "2026-04-10T12:05:01+00:00"


def test_poll_nvd_uses_api_key_when_credentials_present(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    # Inject required env vars before constructing Settings (same pattern as test_canonical_mapper)
    monkeypatch.setenv("SECRET_KEY", "testsecretkey_atleast32charslong_1234")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
    from app.crypto import encrypt_credentials
    from app.config import Settings
    test_settings = Settings()
    from app.workers import nvd as nvd_module

    sid = uuid.uuid4()
    blob = encrypt_credentials(test_settings.SECRET_KEY, {"type": "apiKey", "key": "NVD-KEY-xxx"})
    source = {"id": sid, "credentials_enc": blob, "last_cursor": None}

    # Patch settings in the nvd module so decrypt_credentials uses the same key
    monkeypatch.setattr("app.config.settings", test_settings)

    calls = _install_common_mocks(monkeypatch, [], source)

    nvd_module.poll_nvd_impl(str(sid))
    assert calls["search_kwargs"][0]["key"] == "NVD-KEY-xxx"


def test_poll_nvd_no_api_key_when_credentials_null(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workers import nvd as nvd_module
    sid = uuid.uuid4()
    source = {"id": sid, "credentials_enc": None, "last_cursor": None}
    calls = _install_common_mocks(monkeypatch, [], source)

    nvd_module.poll_nvd_impl(str(sid))
    assert calls["search_kwargs"][0].get("key") is None


def test_poll_nvd_writes_cve_details_row(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import nvd as nvd_module
    sid = uuid.uuid4()
    source = {"id": sid, "credentials_enc": None, "last_cursor": None}
    calls = _install_common_mocks(monkeypatch, [_fake_cve_from_fixture()], source)

    nvd_module.poll_nvd_impl(str(sid))
    assert calls["cve_details"] == 1


def test_poll_nvd_writes_attack_tag_on_t1190(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import nvd as nvd_module
    sid = uuid.uuid4()
    source = {"id": sid, "credentials_enc": None, "last_cursor": None}
    calls = _install_common_mocks(monkeypatch, [_fake_cve_from_fixture()], source)

    nvd_module.poll_nvd_impl(str(sid))
    assert ("T1190", "https://attack.mitre.org/techniques/T1190/") in calls["attack_tags"]


def test_poll_nvd_429_backoff_then_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import nvd as nvd_module
    sleeps: list[int] = []
    monkeypatch.setattr(nvd_module.time, "sleep", lambda s: sleeps.append(s))

    def boom_429(**kwargs):
        err = _NvdError("429 Too Many Requests", 429)
        raise err
    monkeypatch.setattr(nvd_module.nvdlib, "searchCVE_V2", boom_429)

    sid = uuid.uuid4()
    monkeypatch.setattr(nvd_module, "_fetch_source_row", lambda s, sid: {
        "id": sid, "credentials_enc": None, "last_cursor": None,
    })
    monkeypatch.setattr(nvd_module, "_open_session", _fake_session_ctx_nvd)
    health: list = []
    monkeypatch.setattr(nvd_module, "update_source_health",
                        lambda s, sid, *, status, succeeded: health.append((status, succeeded)))
    monkeypatch.setattr(nvd_module, "_advance_cursor", lambda *a, **kw: None)

    nvd_module.poll_nvd_impl(str(sid))
    assert sleeps == [30, 60, 120]
    assert health == [("rate_limited", False)]


def test_poll_nvd_5xx_uses_same_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import nvd as nvd_module
    sleeps: list[int] = []
    monkeypatch.setattr(nvd_module.time, "sleep", lambda s: sleeps.append(s))

    def boom_502(**kwargs):
        raise _NvdError("502 Bad Gateway", 502)
    monkeypatch.setattr(nvd_module.nvdlib, "searchCVE_V2", boom_502)

    sid = uuid.uuid4()
    monkeypatch.setattr(nvd_module, "_fetch_source_row", lambda s, sid: {
        "id": sid, "credentials_enc": None, "last_cursor": None,
    })
    monkeypatch.setattr(nvd_module, "_open_session", _fake_session_ctx_nvd)
    health: list = []
    monkeypatch.setattr(nvd_module, "update_source_health",
                        lambda s, sid, *, status, succeeded: health.append((status, succeeded)))
    monkeypatch.setattr(nvd_module, "_advance_cursor", lambda *a, **kw: None)

    nvd_module.poll_nvd_impl(str(sid))
    assert sleeps == [30, 60, 120]
    assert health[-1] == ("http_error", False)


def test_poll_nvd_4xx_non_429_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import nvd as nvd_module
    sleeps: list[int] = []
    monkeypatch.setattr(nvd_module.time, "sleep", lambda s: sleeps.append(s))

    def boom_404(**kwargs):
        raise _NvdError("404 Not Found", 404)
    monkeypatch.setattr(nvd_module.nvdlib, "searchCVE_V2", boom_404)

    sid = uuid.uuid4()
    monkeypatch.setattr(nvd_module, "_fetch_source_row", lambda s, sid: {
        "id": sid, "credentials_enc": None, "last_cursor": None,
    })
    monkeypatch.setattr(nvd_module, "_open_session", _fake_session_ctx_nvd)
    health: list = []
    monkeypatch.setattr(nvd_module, "update_source_health",
                        lambda s, sid, *, status, succeeded: health.append((status, succeeded)))
    monkeypatch.setattr(nvd_module, "_advance_cursor", lambda *a, **kw: None)

    nvd_module.poll_nvd_impl(str(sid))
    assert sleeps == []  # D-30: 4xx non-429 fails fast
    assert health == [("http_error", False)]


def test_poll_nvd_cursor_not_advanced_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import nvd as nvd_module
    monkeypatch.setattr(nvd_module.time, "sleep", lambda s: None)

    def boom(**kwargs):
        raise _NvdError("400 Bad Request", 400)
    monkeypatch.setattr(nvd_module.nvdlib, "searchCVE_V2", boom)

    sid = uuid.uuid4()
    monkeypatch.setattr(nvd_module, "_fetch_source_row", lambda s, sid: {
        "id": sid, "credentials_enc": None, "last_cursor": "2026-01-01T00:00:00+00:00",
    })
    monkeypatch.setattr(nvd_module, "_open_session", _fake_session_ctx_nvd)
    monkeypatch.setattr(nvd_module, "update_source_health", lambda *a, **kw: None)

    cursor_advances: list = []
    monkeypatch.setattr(nvd_module, "_advance_cursor",
                        lambda s, sid, cur: cursor_advances.append(cur))

    nvd_module.poll_nvd_impl(str(sid))
    assert cursor_advances == []  # no cursor advance on failure
