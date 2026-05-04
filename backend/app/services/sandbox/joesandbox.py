"""Joe Sandbox provider — Phase 27."""
from __future__ import annotations
import logging
import httpx
from app.services.sandbox import SandboxReport

log = logging.getLogger(__name__)
PROVIDER = "joesandbox"
_BASE = "https://jbxcloud.joesecurity.org/api/v2"


async def submit(
    client: httpx.AsyncClient,
    sha256: str,
    api_key: str,
    options: dict | None = None,
) -> str:
    resp = await client.post(
        f"{_BASE}/analysis/submit",
        headers={"ApiKey": api_key},
        json={"sample_hash": sha256, "comments": "IntelliBird Phase 27"},
        timeout=15.0,
    )
    resp.raise_for_status()
    return str(resp.json().get("webid", ""))


async def poll(
    client: httpx.AsyncClient,
    job_id: str,
    api_key: str,
    options: dict | None = None,
) -> SandboxReport | None:
    try:
        resp = await client.get(
            f"{_BASE}/analysis/info/{job_id}",
            headers={"ApiKey": api_key},
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
    if data.get("status") != "finished":
        return None
    return _normalise(data)


def _normalise(data: dict) -> SandboxReport:
    score = int(data.get("score", 0))
    verdict = data.get("classification", "unknown").lower()
    iocs = [n.get("host", "") for n in data.get("contacted_hosts", []) if n.get("host")]
    techniques = [t["id"] for t in data.get("mitre_attack", []) if t.get("id")]
    return SandboxReport(
        techniques=techniques,
        network_iocs=iocs,
        process_tree=data.get("processes", {}),
        score=score,
        verdict=verdict,
        raw_json=data,
    )
