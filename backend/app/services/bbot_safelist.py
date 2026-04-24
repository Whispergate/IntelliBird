"""BBOT module safelist (M-3 pitfall closure).

BBOT 2.8.x stable-passive modules. Verified via `docker run --rm blacklanternsecurity/bbot:stable -l`
on 2026-04-20 (see docs/research/bbot-module-verification.md for full tabular output and
sha256 image digest: ae34a24ee3f30eb334466450303dc2df739b5505aa0c248fa0f603b167f0fc69).

Backend is the SOLE source of truth — UI populates its module multi-select from
GET /api/easm/safelist which reads this module. Any non-safelist module in a scan
request is rejected at the router layer with HTTP 422.

Pitfall closures applied:
  M-3: Module safelist is server-side frozenset — no runtime mutation possible.
  §Pitfall 3: sublist3r is NOT in BBOT 2.8.4 and MUST NOT be included.
  §Pitfall 3: Module name is 'crt' (not 'crt.sh'); 'subdomaincenter' (not 'subdomains').
"""
from __future__ import annotations

from app.config import settings

# ---------------------------------------------------------------------------
# BBOT version pin (locked to verified image digest in docs/research/bbot-module-verification.md)
# ---------------------------------------------------------------------------
BBOT_VERSION: str = "2.8.4"
BBOT_IMAGE_DIGEST: str = (
    "sha256:ae34a24ee3f30eb334466450303dc2df739b5505aa0c248fa0f603b167f0fc69"
)

# ---------------------------------------------------------------------------
# Verified 14-module passive-safe set from docs/research/bbot-module-verification.md.
# Names marked (*) require an API key; BBOT skips them silently when credentials absent.
# DO NOT ADD 'sublist3r' — it was removed from BBOT 2.8.x (PITFALLS §Pitfall 3).
# DO NOT USE 'crt.sh' — the actual BBOT module name is 'crt'.
# ---------------------------------------------------------------------------
BBOT_STABLE_PASSIVE_MODULES: frozenset[str] = frozenset({
    "crt",               # crt.sh certificate transparency (name is "crt" NOT "crt.sh")
    "dnsdumpster",       # dnsdumpster.com passive DNS
    "otx",               # (*) AlienVault OTX — requires OTX_API_KEY
    "shodan_dns",        # (*) Shodan passive DNS — requires SHODAN_API_KEY
    "wayback",           # archive.org Wayback Machine
    "github_codesearch", # (*) GitHub code search — requires GITHUB_TOKEN
    "certspotter",       # Certspotter CT logs
    "hackertarget",      # hackertarget.com API
    "anubisdb",          # jldc.me subdomain database
    "bevigil",           # (*) OSINT from mobile apps — requires BEVIGIL_API_KEY
    "chaos",             # (*) ProjectDiscovery Chaos — requires CHAOS_API_KEY
    "urlscan",           # urlscan.io
    "securitytrails",    # (*) SecurityTrails — requires SECURITYTRAILS_API_KEY
    "subdomaincenter",   # subdomain.center API — replaces CONTEXT.md "sublist3r"/"subdomains"
})

# ---------------------------------------------------------------------------
# Module -> easm_credential_provider ENUM value mapping (aligns with migration 010).
# Modules NOT in this dict run without credentials (BBOT skips them silently if absent).
# ---------------------------------------------------------------------------
MODULE_CREDENTIAL_REQUIREMENTS: dict[str, str] = {
    "otx": "otx",
    "shodan_dns": "shodan",
    "github_codesearch": "github",
    "bevigil": "bevigil",
    "chaos": "chaos",
    "securitytrails": "securitytrails",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_effective_safelist() -> frozenset[str]:
    """Return BBOT_STABLE_PASSIVE_MODULES unioned with BBOT_EXPERIMENTAL_OVERRIDE.

    BBOT_EXPERIMENTAL_OVERRIDE is a comma-separated string of additional module names
    (empty by default). Read at call time from the Pydantic Settings singleton (cheap).

    This is the ONLY supported path for extending the module set at runtime.
    Operators should prefer updating the verified safelist and redeploying.
    """
    override_raw: str = (settings.BBOT_EXPERIMENTAL_OVERRIDE or "").strip()
    if not override_raw:
        return BBOT_STABLE_PASSIVE_MODULES
    extras: frozenset[str] = frozenset(
        m.strip() for m in override_raw.split(",") if m.strip()
    )
    return BBOT_STABLE_PASSIVE_MODULES | extras


def validate_modules(requested: list[str]) -> tuple[bool, list[str]]:
    """Validate that all requested modules are in the effective safelist.

    Returns:
        (all_valid, invalid_names) — if all_valid is True, invalid_names is [].

    Used by the EASM scan router to return HTTP 422 with the invalid names listed.
    UI-SPEC canonical error copy:
      'One or more selected modules are not in the stable safelist: <names>. Remove them and retry.'
    """
    effective: frozenset[str] = get_effective_safelist()
    invalid: list[str] = sorted({m for m in requested if m not in effective})
    return (len(invalid) == 0), invalid
