"""graph_traversal dashboard_roles claim-based visibility — AUTH-02 / C-2."""
from __future__ import annotations

from app.services.graph_traversal import _visibility_ok


def test_shared_visible_without_roles():
    assert _visibility_ok("shared", None) is True
    assert _visibility_ok("shared", []) is True


def test_red_only_visible_to_red_dashboard():
    assert _visibility_ok("red_only", ["red"]) is True
    assert _visibility_ok("red_only", ["blue"]) is False
    assert _visibility_ok("red_only", ["red", "blue"]) is True


def test_blue_only_visible_to_blue_dashboard():
    assert _visibility_ok("blue_only", ["blue"]) is True
    assert _visibility_ok("blue_only", ["red"]) is False
    assert _visibility_ok("blue_only", ["red", "blue"]) is True


def test_shared_always_visible_when_any_role():
    for roles in ([], ["red"], ["blue"], ["red", "blue"], None):
        assert _visibility_ok("shared", roles) is True


def test_empty_list_no_filter():
    """Empty dashboard_roles list = unauthenticated = pass through."""
    assert _visibility_ok("red_only", []) is True
    assert _visibility_ok("blue_only", []) is True
