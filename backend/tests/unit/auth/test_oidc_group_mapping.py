"""OIDC groups -> role mapping unit tests — AUTH-01."""
from __future__ import annotations

from app.security.oidc import map_groups_to_role


def test_admin_group_match():
    assert map_groups_to_role(
        ["intellibird-admins"],
        admin_groups="intellibird-admins",
        analyst_groups="",
        viewer_groups="",
    ) == "Admin"


def test_analyst_group_match():
    assert map_groups_to_role(
        ["intellibird-analysts"],
        admin_groups="",
        analyst_groups="intellibird-analysts",
        viewer_groups="",
    ) == "Analyst"


def test_default_viewer_on_no_match():
    assert map_groups_to_role(
        ["org:other-team"],
        admin_groups="intellibird-admins",
        analyst_groups="intellibird-analysts",
        viewer_groups="",
    ) == "Viewer"


def test_empty_groups_claim_returns_viewer():
    assert map_groups_to_role(
        [],
        admin_groups="a,b",
        analyst_groups="c,d",
        viewer_groups="e",
    ) == "Viewer"


def test_admin_beats_analyst_precedence():
    """User in both admin and analyst groups resolves to Admin."""
    assert map_groups_to_role(
        ["intellibird-admins", "intellibird-analysts"],
        admin_groups="intellibird-admins",
        analyst_groups="intellibird-analysts",
        viewer_groups="",
    ) == "Admin"


def test_comma_separated_settings_parsed():
    """Whitespace-stripped set membership."""
    assert map_groups_to_role(
        ["b"],
        admin_groups="a, b , c",
        analyst_groups="",
        viewer_groups="",
    ) == "Admin"


def test_none_settings_no_match():
    assert map_groups_to_role(
        ["intellibird-admins"],
        admin_groups=None,
        analyst_groups=None,
        viewer_groups=None,
    ) == "Viewer"
