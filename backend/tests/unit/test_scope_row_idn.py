"""Unit tests for IDN field validators on ScopeRowCreate / ScopeRowUpdate.

Covers UX-03 requirement: backend Pydantic validator transparently encodes
unicode FQDN values to punycode for domain and certificate scope types.


"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.projects import ScopeRowCreate, ScopeRowUpdate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_create(scope_type: str, value: str, **kwargs) -> ScopeRowCreate:
    """Convenience wrapper — intel_scope defaults to True so the at-least-one-flag
    validator passes without needing it in every test call."""
    return ScopeRowCreate(
        scope_type=scope_type,
        value=value,
        intel_scope=kwargs.pop("intel_scope", True),
        active_test_scope=kwargs.pop("active_test_scope", False),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# ScopeRowCreate tests
# ---------------------------------------------------------------------------


def test_unicode_to_punycode():
    """Unicode FQDN for domain scope_type is transparently encoded to punycode."""
    row = _make_create("domain", "bücher.example")
    assert row.value == "xn--bcher-kva.example", (
        f"Expected punycode 'xn--bcher-kva.example', got {row.value!r}"
    )


def test_ascii_passthrough():
    """ASCII domain value passes through unchanged (idempotent)."""
    row = _make_create("domain", "example.com")
    assert row.value == "example.com"


def test_punycode_passthrough():
    """Already-punycode value passes through unchanged (idempotent)."""
    row = _make_create("domain", "xn--bcher-kva.example")
    assert row.value == "xn--bcher-kva.example"


def test_invalid_idn_raises_422():
    """Syntactically invalid domain raises ValidationError with 'Invalid IDN' detail."""
    with pytest.raises(ValidationError) as exc_info:
        _make_create("domain", "invalid-.example")
    # The error message must contain the IDN error marker
    errors = exc_info.value.errors()
    assert any("Invalid IDN" in str(e.get("msg", "")) for e in errors), (
        f"Expected 'Invalid IDN' in errors, got: {errors}"
    )


def test_non_fqdn_scope_skips_idn():
    """Non-FQDN scope types (keyword) do not have IDN encoding applied.

    'bücher' is valid as a keyword (it's not a domain), so it passes through unchanged.
    """
    row = _make_create("keyword", "bücher")
    assert row.value == "bücher", (
        f"Expected keyword value unchanged, got {row.value!r}"
    )


def test_certificate_scope_encodes():
    """certificate scope_type (FQDN-bearing per CONTEXT.md §UX-03) encodes unicode to punycode."""
    row = _make_create("certificate", "bücher.example")
    assert row.value == "xn--bcher-kva.example", (
        f"Expected punycode for certificate scope, got {row.value!r}"
    )


def test_idnaerror_subclass_caught():
    """IDNAError subclass (InvalidCodepoint) is caught and re-raised as ValueError → 422.

    Null byte in domain name is rejected as an invalid code point.
    """
    with pytest.raises(ValidationError) as exc_info:
        _make_create("domain", "bücher\x00.example")
    errors = exc_info.value.errors()
    assert any("Invalid IDN" in str(e.get("msg", "")) for e in errors), (
        f"Expected 'Invalid IDN' in errors for null-byte domain, got: {errors}"
    )


# ---------------------------------------------------------------------------
# ScopeRowUpdate tests
# ---------------------------------------------------------------------------


def test_update_partial_value():
    """ScopeRowUpdate with scope_type='domain' and unicode value encodes to punycode.

    The model_validator fires on partial updates that include an FQDN value,
    providing the same encoding guarantee as ScopeRowCreate.
    """
    row = ScopeRowUpdate(scope_type="domain", value="bücher.example")
    assert row.value == "xn--bcher-kva.example", (
        f"ScopeRowUpdate: expected punycode, got {row.value!r}"
    )


def test_update_no_value_no_encoding():
    """ScopeRowUpdate without a value field is unaffected by the IDN validator."""
    row = ScopeRowUpdate(scope_type="domain", exclude=True)
    assert row.value is None
    assert row.exclude is True


def test_update_no_scope_type_no_encoding():
    """ScopeRowUpdate without scope_type does not trigger IDN encoding even if value present.

    scope_type is None → _FQDN_SCOPE_TYPES check is False → value passes through.
    """
    row = ScopeRowUpdate(value="bücher.example")
    # value is stored raw — no scope_type means no encoding context
    assert row.value == "bücher.example"
