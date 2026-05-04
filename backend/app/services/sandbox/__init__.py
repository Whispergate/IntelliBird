"""
Phase 27 — Sandbox provider abstraction.
SandboxReport: common normalised result schema.
get_provider_module(): dispatch to provider module by name.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class SandboxReport:
    """Normalised sandbox analysis result — common schema across all providers."""
    techniques: list[str] = field(default_factory=list)      # MITRE ATT&CK IDs e.g. ["T1059.001"]
    network_iocs: list[str] = field(default_factory=list)    # IPs, domains, URLs observed
    process_tree: dict = field(default_factory=dict)         # Provider-native process tree JSON
    score: int = 0                                            # 0-100 maliciousness score
    verdict: str = "unknown"                                  # clean / suspicious / malicious / unknown
    raw_json: dict = field(default_factory=dict)             # Full provider response (stored in report_json)


_PROVIDER_MAP: dict[str, str] = {
    "cuckoo": "app.services.sandbox.cuckoo",
    "anyrun": "app.services.sandbox.anyrun",
    "joesandbox": "app.services.sandbox.joesandbox",
    "hybridanalysis": "app.services.sandbox.hybridanalysis",
    "triage": "app.services.sandbox.triage",
}


def get_provider_module(provider: str):
    """Return the provider module for the given provider name.
    Raises ValueError for unknown providers.
    """
    import importlib
    mod_path = _PROVIDER_MAP.get(provider)
    if not mod_path:
        raise ValueError(f"Unknown sandbox provider: {provider!r}. Supported: {list(_PROVIDER_MAP)}")
    return importlib.import_module(mod_path)
