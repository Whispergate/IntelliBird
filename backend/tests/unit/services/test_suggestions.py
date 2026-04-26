"""Unit tests for the suggestion validator gate — Phase 17 / AI-03.

Covers:
  test_cve_validation     — CVE-ID regex + cve_details cache lookup
  test_attck_validation   — ATT&CK technique-ID regex + attack_techniques lookup
  test_actor_sdo_match    — threat-actor name matched against events SDO rows
  test_silent_reject      — mixed input; invalid candidates logged and dropped

These are pure-unit tests: the SQLAlchemy async session is mocked so no DB
container is needed.  The session mock is structured to mirror what
AsyncSession.execute().scalar_one_or_none() returns in production code.
"""
from __future__ import annotations

import logging
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# --- bootstrap env vars before any app.* import ----------------------------
os.environ.setdefault("SECRET_KEY", "x" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "y" * 64)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from app.services.llm.suggestion_validator import (  # noqa: E402
    ATTCK_REGEX,
    CVE_REGEX,
    validate_and_stage_suggestions,
    validate_actor_name,
    validate_attack_technique,
    validate_cve,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db(scalar_result: object = None) -> AsyncMock:
    """Return an AsyncMock session whose execute().scalar_one_or_none() returns
    *scalar_result*.  Pass a model instance to simulate a cache hit, or None
    to simulate a miss."""
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = scalar_result

    db = AsyncMock()
    db.execute.return_value = result_mock
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _sentinel() -> MagicMock:
    """A non-None sentinel object that counts as a 'row found' result."""
    return MagicMock()


# ---------------------------------------------------------------------------
# test_cve_validation
# ---------------------------------------------------------------------------

async def test_cve_validation() -> None:
    """CVE ID passes regex AND cve_details cache lookup before staging."""
    # --- Valid format + present in cache → True ---
    db_hit = _mock_db(scalar_result=_sentinel())
    assert await validate_cve(db_hit, "CVE-2024-12345") is True
    db_hit.execute.assert_awaited_once()

    # --- Valid format but absent from cache → False ---
    db_miss = _mock_db(scalar_result=None)
    assert await validate_cve(db_miss, "CVE-2024-99999") is False
    db_miss.execute.assert_awaited_once()

    # --- Malformed ID (year too short) → False; no DB query at all ---
    db_no_call = _mock_db(scalar_result=_sentinel())
    assert await validate_cve(db_no_call, "CVE-24-1") is False
    db_no_call.execute.assert_not_awaited()

    # --- CVE_REGEX spot checks ---
    assert CVE_REGEX.match("CVE-2024-12345") is not None
    assert CVE_REGEX.match("CVE-2024-1234567") is not None  # 7-digit allowed
    assert CVE_REGEX.match("CVE-24-12345") is None
    assert CVE_REGEX.match("cve-2024-12345") is None  # lowercase rejected
    assert CVE_REGEX.match("CVE-2024-123") is None    # only 3 digits — too short


# ---------------------------------------------------------------------------
# test_attck_validation
# ---------------------------------------------------------------------------

async def test_attck_validation() -> None:
    """ATT&CK technique ID passes regex AND attack_techniques table lookup."""
    # T1566 + present → True
    db_hit = _mock_db(scalar_result=_sentinel())
    assert await validate_attack_technique(db_hit, "T1566") is True
    db_hit.execute.assert_awaited_once()

    # T1566.001 (sub-technique) + present → True
    db_hit2 = _mock_db(scalar_result=_sentinel())
    assert await validate_attack_technique(db_hit2, "T1566.001") is True
    db_hit2.execute.assert_awaited_once()

    # T9999 passes regex but is absent from catalog → False
    db_miss = _mock_db(scalar_result=None)
    assert await validate_attack_technique(db_miss, "T9999") is False
    db_miss.execute.assert_awaited_once()

    # "T123" fails regex (only 3 digits) → False; no DB query
    db_no_call = _mock_db(scalar_result=_sentinel())
    assert await validate_attack_technique(db_no_call, "T123") is False
    db_no_call.execute.assert_not_awaited()

    # --- ATTCK_REGEX spot checks ---
    assert ATTCK_REGEX.match("T1566") is not None
    assert ATTCK_REGEX.match("T1566.001") is not None
    assert ATTCK_REGEX.match("T123") is None     # too few digits
    assert ATTCK_REGEX.match("T12345") is None   # five digits — rejected
    assert ATTCK_REGEX.match("T1566.01") is None # sub-technique must be 3 digits


# ---------------------------------------------------------------------------
# test_actor_sdo_match
# ---------------------------------------------------------------------------

async def test_actor_sdo_match() -> None:
    """Threat-actor name is validated against existing threat-actor STIX SDO events."""
    # APT28 exists as a threat-actor SDO row (stix_type='threat-actor', title='APT28')
    db_hit = _mock_db(scalar_result=_sentinel())
    assert await validate_actor_name(db_hit, "APT28") is True
    db_hit.execute.assert_awaited_once()

    # Novel name with no SDO → False (strict — no relaxed fallback)
    db_miss = _mock_db(scalar_result=None)
    assert await validate_actor_name(db_miss, "FictionalActorXYZ") is False
    db_miss.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# test_silent_reject
# ---------------------------------------------------------------------------

async def test_silent_reject(caplog: pytest.LogCaptureFixture) -> None:
    """Failed validation drops suggestion silently (logs INFO, never inserts row).

    Mixed input:
      - ("cve",    "CVE-2024-12345")  → valid CVE   → should be staged
      - ("attack", "T1566")           → valid ATT&CK → should be staged
      - ("cve",    "CVE-24-1")        → malformed    → dropped (INFO logged)
      - ("actor",  "UnknownActor")    → no SDO match → dropped (INFO logged)
    """
    summary_id = uuid.uuid4()
    project_id = uuid.uuid4()
    event_id = uuid.uuid4()

    # We need per-call DB mock behaviour:
    #   call 1 (CVE-2024-12345): row found → valid
    #   call 2 (T1566):          row found → valid
    #   CVE-24-1 regex fails → no DB call
    #   call 3 (UnknownActor):   row not found → invalid
    sentinel = _sentinel()
    result_hit = MagicMock()
    result_hit.scalar_one_or_none.return_value = sentinel
    result_miss = MagicMock()
    result_miss.scalar_one_or_none.return_value = None

    db = AsyncMock()
    # execute is called for: CVE-2024-12345 (hit), T1566 (hit), UnknownActor (miss)
    db.execute.side_effect = [result_hit, result_hit, result_miss]
    db.add = MagicMock()
    db.flush = AsyncMock()

    candidates = [
        ("cve", "CVE-2024-12345"),
        ("attack", "T1566"),
        ("cve", "CVE-24-1"),        # malformed — dropped before DB call
        ("actor", "UnknownActor"),  # no SDO → dropped
    ]

    with caplog.at_level(logging.INFO, logger="app.services.llm.suggestion_validator"):
        staged = await validate_and_stage_suggestions(
            db,
            ai_summary_id=summary_id,
            project_id=project_id,
            event_id=event_id,
            candidates=candidates,
        )

    # Only 2 valid suggestions were staged
    assert len(staged) == 2, f"Expected 2 staged suggestions, got {len(staged)}"
    assert staged[0].value == "CVE-2024-12345"
    assert staged[0].suggestion_type == "cve"
    assert staged[0].status == "pending"
    assert staged[1].value == "T1566"
    assert staged[1].suggestion_type == "attack"

    # db.add was called exactly twice (once per valid suggestion)
    assert db.add.call_count == 2, (
        f"Expected db.add called 2 times, got {db.add.call_count}"
    )

    # db.flush was called once at the end
    db.flush.assert_awaited_once()

    # INFO log emitted for the two invalid candidates
    info_records = [
        r for r in caplog.records
        if r.name == "app.services.llm.suggestion_validator" and r.levelno == logging.INFO
    ]
    assert len(info_records) == 2, (
        f"Expected 2 INFO log records for rejected candidates, got {len(info_records)}"
    )
