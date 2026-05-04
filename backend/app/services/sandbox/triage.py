"""Hatching Triage sandbox provider — Phase 27."""
from __future__ import annotations
import logging
import httpx
from app.services.sandbox import SandboxReport

log = logging.getLogger(__name__)
PROVIDER = "triage"
_BASE = "https://tria.ge/api/v0"


async def submit(
    client: httpx.AsyncClient,
    sha256: str,
    api_key: str,
    options: dict | None = None,
) -> str:
    resp = await client.post(
        f"{_BASE}/samples",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"kind": "file", "_hash": sha256, "interactive": False},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json().get("id", "")


async def poll(
    client: httpx.AsyncClient,
    job_id: str,
    api_key: str,
    options: dict | None = None,
) -> SandboxReport | None:
    try:
        resp = await client.get(
            f"{_BASE}/samples/{job_id}/summary",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
    except (httpx.TimeoutException, httpx.RequestError):
        return None
    if resp.status_code == 404:
        return None
    if resp.status_code in (401, 403):
        resp.raise_for_status()
    if not resp.is_success:
        return None
    data = resp.json()
    if data.get("status") not in ("reported", "static_analysis"):
        return None
    return _normalise(data)


def _normalise(data: dict) -> SandboxReport:
    score = int(data.get("score", 0))
    verdict = "malicious" if score >= 7 else "suspicious" if score >= 4 else "clean"
    targets = data.get("targets", [])
    iocs = []
    techniques = []
    for t in targets:
        for sig in t.get("signatures", []):
            for ttp in sig.get("ttp", []):
                techniques.append(ttp)
        for ioc in t.get("iocs", {}).get("ips", []):
            iocs.append(ioc)
        for ioc in t.get("iocs", {}).get("domains", []):
            iocs.append(ioc)
    return SandboxReport(
        techniques=list(set(techniques)),
        network_iocs=list(set(iocs)),
        process_tree=data.get("processes", {}),
        score=score * 10,  # Triage uses 0-10; normalise to 0-100
        verdict=verdict,
        raw_json=data,
    )
