"""Hybrid Analysis sandbox provider — Phase 27."""
from __future__ import annotations
import logging
import httpx
from app.services.sandbox import SandboxReport

log = logging.getLogger(__name__)
PROVIDER = "hybridanalysis"
_BASE = "https://www.hybrid-analysis.com/api/v2"


async def submit(
    client: httpx.AsyncClient,
    sha256: str,
    api_key: str,
    options: dict | None = None,
) -> str:
    resp = await client.post(
        f"{_BASE}/quick-scan/hash-list",
        headers={"api-key": api_key, "User-Agent": "IntelliBird/4.0 Falcon Sandbox"},
        json={"scan_type": "all", "hashes": [sha256]},
        timeout=15.0,
    )
    resp.raise_for_status()
    results = resp.json().get("result", [])
    if results:
        return str(results[0].get("job_id", ""))
    return ""


async def poll(
    client: httpx.AsyncClient,
    job_id: str,
    api_key: str,
    options: dict | None = None,
) -> SandboxReport | None:
    try:
        resp = await client.get(
            f"{_BASE}/report/{job_id}/summary",
            headers={"api-key": api_key, "User-Agent": "IntelliBird/4.0 Falcon Sandbox"},
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
    if data.get("state") not in ("SUCCESS", "success"):
        return None
    return _normalise(data)


def _normalise(data: dict) -> SandboxReport:
    score = int(data.get("threat_score", 0))
    verdict = data.get("verdict", "unknown").lower()
    iocs = (
        [h for h in data.get("hosts", [])]
        + [d for d in data.get("domains", [])]
    )
    techniques = [m["technique_id"] for m in data.get("mitre_attcks", []) if m.get("technique_id")]
    return SandboxReport(
        techniques=techniques,
        network_iocs=iocs,
        process_tree=data.get("processes", {}),
        score=score,
        verdict=verdict,
        raw_json=data,
    )
