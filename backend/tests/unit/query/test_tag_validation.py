"""Tests for TAG_REGEX + TagPatchRequest validator — FIL-03 /."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.tags import TAG_REGEX, TagPatchRequest


def test_valid_tag_passes():
    assert TAG_REGEX.match("apt28")
    assert TAG_REGEX.match("a")
    assert TAG_REGEX.match("with-dash_under1")


def test_uppercase_tag_lowercased_by_validator():
    r = TagPatchRequest(add=["APT28"], remove=[])
    assert r.add == ["apt28"]


def test_mixed_case_tag_lowercased():
    r = TagPatchRequest(add=["Phishing"], remove=["OldTAG"])
    assert r.add == ["phishing"]
    assert r.remove == ["oldtag"]


def test_invalid_chars_rejected():
    with pytest.raises(ValidationError):
        TagPatchRequest(add=["bad!tag"], remove=[])
    with pytest.raises(ValidationError):
        TagPatchRequest(add=["tag with space"], remove=[])
    with pytest.raises(ValidationError):
        TagPatchRequest(add=["tag/slash"], remove=[])


def test_over_32_chars_rejected():
    long = "a" * 33
    with pytest.raises(ValidationError):
        TagPatchRequest(add=[long], remove=[])


def test_empty_tag_rejected():
    with pytest.raises(ValidationError):
        TagPatchRequest(add=[""], remove=[])


def test_non_string_rejected():
    with pytest.raises(ValidationError):
        TagPatchRequest(add=[123], remove=[])  # type: ignore[list-item]


def test_invalid_in_remove_also_rejects_whole_request():
    with pytest.raises(ValidationError):
        TagPatchRequest(add=["ok"], remove=["BAD!"])


def test_empty_lists_are_valid():
    r = TagPatchRequest(add=[], remove=[])
    assert r.add == []
    assert r.remove == []


def test_regex_accepts_digits_only():
    assert TAG_REGEX.match("123")
    r = TagPatchRequest(add=["2025"], remove=[])
    assert r.add == ["2025"]


def test_32_chars_exactly_accepted():
    at_limit = "a" * 32
    r = TagPatchRequest(add=[at_limit], remove=[])
    assert r.add == [at_limit]


def test_underscore_and_dash_in_tag():
    r = TagPatchRequest(add=["my_tag-name"], remove=[])
    assert r.add == ["my_tag-name"]
