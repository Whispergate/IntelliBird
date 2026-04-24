"""Unit tests for preset schemas + name regex — FIL-04."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.presets import (
    PRESET_NAME_REGEX,
    FilterPresetResponse,
    PresetCreate,
    PresetUpsert,
)


def test_preset_name_regex_accepts_valid() -> None:
    for name in ["default-red", "abc123", "with_underscore", "a", "x" * 64]:
        assert PRESET_NAME_REGEX.match(name), f"expected match for {name!r}"


def test_preset_name_regex_rejects_invalid() -> None:
    for name in ["", "UPPERCASE", "bad!char", "with space", "x" * 65, "дом"]:
        assert not PRESET_NAME_REGEX.match(name), f"expected no match for {name!r}"


def test_preset_create_lowercase_enforced_via_regex() -> None:
    from app.models.projects import LEGACY_PROJECT_ID
    with pytest.raises(ValidationError):
        PresetCreate(name="UPPERCASE", query_params={}, project_id=LEGACY_PROJECT_ID)


def test_preset_create_over_64_chars_rejected() -> None:
    from app.models.projects import LEGACY_PROJECT_ID
    with pytest.raises(ValidationError):
        PresetCreate(name="x" * 65, query_params={}, project_id=LEGACY_PROJECT_ID)


def test_preset_create_accepts_valid_params() -> None:
    from app.models.projects import LEGACY_PROJECT_ID
    p = PresetCreate(
        name="default-red",
        query_params={"source_type": ["rss"]},
        project_id=LEGACY_PROJECT_ID,
    )
    assert p.name == "default-red"
    assert p.query_params == {"source_type": ["rss"]}
    assert p.project_id == LEGACY_PROJECT_ID


def test_preset_upsert_has_no_name_field() -> None:
    p = PresetUpsert(query_params={"tlp": ["clear"]})
    assert not hasattr(p, "name")


def test_preset_response_requires_all_fields() -> None:
    from app.models.projects import LEGACY_PROJECT_ID
    r = FilterPresetResponse(
        id=uuid.uuid4(),
        name="example",
        project_id=LEGACY_PROJECT_ID,
        query_params={"x": 1},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    assert r.name == "example"


def test_preset_create_requires_non_empty_name() -> None:
    from app.models.projects import LEGACY_PROJECT_ID
    with pytest.raises(ValidationError):
        PresetCreate(name="", query_params={}, project_id=LEGACY_PROJECT_ID)


def test_preset_create_rejects_special_chars() -> None:
    from app.models.projects import LEGACY_PROJECT_ID
    with pytest.raises(ValidationError):
        PresetCreate(name="bad!char", query_params={}, project_id=LEGACY_PROJECT_ID)


def test_preset_create_rejects_spaces() -> None:
    from app.models.projects import LEGACY_PROJECT_ID
    with pytest.raises(ValidationError):
        PresetCreate(name="has space", query_params={}, project_id=LEGACY_PROJECT_ID)


def test_preset_upsert_accepts_nested_query_params() -> None:
    p = PresetUpsert(query_params={"tlp": ["clear", "green"], "source_type": ["rss", "nvd"]})
    assert p.query_params["tlp"] == ["clear", "green"]


def test_preset_name_regex_accepts_hyphens_and_underscores() -> None:
    assert PRESET_NAME_REGEX.match("default-red-team_v2")


def test_preset_name_regex_rejects_unicode() -> None:
    assert not PRESET_NAME_REGEX.match("дом")
    assert not PRESET_NAME_REGEX.match("café")
