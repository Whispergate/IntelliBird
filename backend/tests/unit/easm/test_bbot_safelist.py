"""Unit tests for bbot_safelist.py - EASM-05 / M-3 safelist closure.

Activated by plan 11-02 (was Wave 0 stub referencing plan 11-04).
"""
from __future__ import annotations

import os

# Pydantic-settings singleton is loaded at import time; inject required env vars
# before any app.* import to prevent ValidationError at collection time.
# Pattern from STATE.md notes.
os.environ.setdefault("SECRET_KEY", "x" * 64)
os.environ.setdefault("JWT_SIGNING_KEY", "y" * 64)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest

from app.services.bbot_safelist import (
    BBOT_STABLE_PASSIVE_MODULES,
    MODULE_CREDENTIAL_REQUIREMENTS,
    get_effective_safelist,
    validate_modules,
)

# Allowed credential provider values (from easm_credential_provider PG ENUM in migration 010)
VALID_CREDENTIAL_PROVIDERS: frozenset[str] = frozenset({
    "shodan",
    "github",
    "bevigil",
    "chaos",
    "securitytrails",
    "otx",
})


class TestSafelistImmutability:
    def test_safelist_is_frozenset(self) -> None:
        """BBOT_STABLE_PASSIVE_MODULES must be a frozenset - not a set or list."""
        assert isinstance(BBOT_STABLE_PASSIVE_MODULES, frozenset), (
            f"Expected frozenset, got {type(BBOT_STABLE_PASSIVE_MODULES)}"
        )

    def test_safelist_is_non_empty(self) -> None:
        """Safelist must contain at least the 14 verified modules."""
        assert len(BBOT_STABLE_PASSIVE_MODULES) >= 14


class TestSafelistContents:
    def test_sublist3r_absent(self) -> None:
        """sublist3r is NOT in BBOT 2.8.4 - must be excluded (PITFALLS §Pitfall 3)."""
        assert "sublist3r" not in BBOT_STABLE_PASSIVE_MODULES, (
            "sublist3r was removed in BBOT 2.8.x - do NOT include it (PITFALLS §Pitfall 3)"
        )

    def test_crt_in_safelist_not_crt_sh(self) -> None:
        """BBOT module name is 'crt', not 'crt.sh' (confirmed in verification doc)."""
        assert "crt" in BBOT_STABLE_PASSIVE_MODULES
        assert "crt.sh" not in BBOT_STABLE_PASSIVE_MODULES

    def test_subdomaincenter_in_safelist(self) -> None:
        """subdomaincenter replaces the non-existent sublist3r + subdomains."""
        assert "subdomaincenter" in BBOT_STABLE_PASSIVE_MODULES

    def test_dnsdumpster_in_safelist(self) -> None:
        assert "dnsdumpster" in BBOT_STABLE_PASSIVE_MODULES

    def test_core_modules_present(self) -> None:
        """Spot-check the 14-module verified set from docs/research/bbot-module-verification.md."""
        expected = {
            "crt", "dnsdumpster", "otx", "shodan_dns", "wayback",
            "github_codesearch", "certspotter", "hackertarget", "anubisdb",
            "bevigil", "chaos", "urlscan", "securitytrails", "subdomaincenter",
        }
        missing = expected - BBOT_STABLE_PASSIVE_MODULES
        assert not missing, f"Missing expected modules: {missing}"


class TestValidateModules:
    def test_validate_modules_all_valid(self) -> None:
        """All modules from the safelist should pass validation."""
        ok, invalid = validate_modules(["crt", "dnsdumpster"])
        assert ok is True
        assert invalid == []

    def test_validate_modules_rejects_experimental(self) -> None:
        """An unknown module must be rejected and returned in the invalid list."""
        ok, invalid = validate_modules(["crt", "nuke_everything"])
        assert ok is False
        assert invalid == ["nuke_everything"]

    def test_validate_modules_rejects_sublist3r(self) -> None:
        """sublist3r must be rejected regardless - it is not in BBOT 2.8.x."""
        ok, invalid = validate_modules(["sublist3r"])
        assert ok is False
        assert "sublist3r" in invalid

    def test_validate_modules_empty_list_is_valid(self) -> None:
        """Empty module list is valid (caller decides minimum-module policy)."""
        ok, invalid = validate_modules([])
        assert ok is True
        assert invalid == []

    def test_validate_modules_all_invalid(self) -> None:
        ok, invalid = validate_modules(["evil1", "evil2"])
        assert ok is False
        assert set(invalid) == {"evil1", "evil2"}

    def test_validate_modules_invalid_names_are_sorted(self) -> None:
        """Invalid names should be returned sorted for deterministic error messages."""
        ok, invalid = validate_modules(["zzz_bad", "aaa_bad"])
        assert ok is False
        assert invalid == sorted(invalid)


class TestGetEffectiveSafelist:
    def test_override_unions_modules(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BBOT_EXPERIMENTAL_OVERRIDE='mymod,othermod' must be unioned into the safelist."""
        from app import config as _cfg
        monkeypatch.setattr(_cfg.settings, "BBOT_EXPERIMENTAL_OVERRIDE", "mymod,othermod")
        effective = get_effective_safelist()
        assert "mymod" in effective
        assert "othermod" in effective
        # Base set still present
        assert "crt" in effective

    def test_override_empty_returns_base_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty BBOT_EXPERIMENTAL_OVERRIDE must return exactly BBOT_STABLE_PASSIVE_MODULES."""
        from app import config as _cfg
        monkeypatch.setattr(_cfg.settings, "BBOT_EXPERIMENTAL_OVERRIDE", "")
        effective = get_effective_safelist()
        assert effective == BBOT_STABLE_PASSIVE_MODULES

    def test_override_whitespace_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Leading/trailing whitespace in the override should not produce empty-string modules."""
        from app import config as _cfg
        monkeypatch.setattr(_cfg.settings, "BBOT_EXPERIMENTAL_OVERRIDE", " mymod , ")
        effective = get_effective_safelist()
        assert "mymod" in effective
        assert "" not in effective


class TestModuleCredentialRequirements:
    def test_module_credential_requirements_all_map_to_valid_providers(self) -> None:
        """Every credential provider listed in MODULE_CREDENTIAL_REQUIREMENTS must be
        a valid value from the easm_credential_provider PG ENUM."""
        for module, provider in MODULE_CREDENTIAL_REQUIREMENTS.items():
            assert provider in VALID_CREDENTIAL_PROVIDERS, (
                f"Module '{module}' maps to unknown provider '{provider}'; "
                f"valid providers: {VALID_CREDENTIAL_PROVIDERS}"
            )

    def test_shodan_dns_requires_shodan_credential(self) -> None:
        assert MODULE_CREDENTIAL_REQUIREMENTS.get("shodan_dns") == "shodan"

    def test_github_codesearch_requires_github_credential(self) -> None:
        assert MODULE_CREDENTIAL_REQUIREMENTS.get("github_codesearch") == "github"
