"""ANY.RUN sandbox provider — Phase 27."""
from __future__ import annotations
import logging
import httpx
from app.services.sandbox import SandboxReport

log = logging.getLogger(__name__)
PROVIDER = "anyrun"
_BASE = "https://api.any.run/v1"


async def submit(
    client: httpx.AsyncClient,
    sha256: str,
    api_key: str,
    options: dict | None = None,
) -> str:
    resp = await client.post(
        f"{_BASE}/analysis",
        headers={"Authorization": f"API-Key {api_key}"},
        json={"obj_type": "file", "obj_url": "", "hash": sha256},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()["data"]["taskid"]


async def poll(
    client: httpx.AsyncClient,
    job_id: str,
    api_key: str,
    options: dict | None = None,
) -> SandboxReport | None:
    try:
        resp = await client.get(
            f"{_BASE}/analysis/{job_id}",
            headers={"Authorization": f"API-Key {api_key}"},
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
    data = resp.json().get("data", {})
    if data.get("status") != "done":
        return None
    return _normalise(data)


def _normalise(data: dict) -> SandboxReport:
    analysis = data.get("analysis", {})
    score = int(analysis.get("scores", {}).get("verdict", {}).get("score", 0))
    verdict = analysis.get("scores", {}).get("verdict", {}).get("verdict", "unknown").lower()
    network = analysis.get("network", {})
    iocs = (
        [c["ip"] for c in network.get("connections", []) if c.get("ip")]
        + [d["domain"] for d in network.get("dns", []) if d.get("domain")]
    )
    techniques = [m["id"] for m in analysis.get("mitre", []) if m.get("id")]
    return SandboxReport(
        techniques=techniques,
        network_iocs=iocs,
        process_tree=data.get("processes", {}),
        score=score,
        verdict=verdict,
        raw_json=data,
    )
