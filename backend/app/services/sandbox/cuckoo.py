"""Cuckoo / CAPEv2 sandbox provider."""
from __future__ import annotations
import logging
import httpx
from app.services.sandbox import SandboxReport

log = logging.getLogger(__name__)
PROVIDER = "cuckoo"

# CAPEv2 REST API defaults; operator configures base_url in sandbox_configs.options
_DEFAULT_BASE = "http://localhost:8090"


async def submit(
    client: httpx.AsyncClient,
    sha256: str,
    api_key: str | None,
    options: dict | None = None,
) -> str:
    """Submit SHA256 hash for analysis. Returns task_id string."""
    base = (options or {}).get("base_url", _DEFAULT_BASE)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    resp = await client.post(
        f"{base}/api/tasks/create/url",
        json={"url": sha256},  # CAPEv2 accepts hash as URL-type submission
        headers=headers,
        timeout=15.0,
    )
    resp.raise_for_status()
    return str(resp.json().get("task_id", ""))


async def poll(
    client: httpx.AsyncClient,
    job_id: str,
    api_key: str | None,
    options: dict | None = None,
) -> SandboxReport | None:
    """Check analysis status. Returns SandboxReport when complete, None when still running."""
    base = (options or {}).get("base_url", _DEFAULT_BASE)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        resp = await client.get(
            f"{base}/api/tasks/report/{job_id}",
            headers=headers,
            timeout=10.0,
        )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        log.warning("cuckoo_poll_error job_id=%s error=%r", job_id, exc)
        return None
    if resp.status_code == 404:
        return None  # Not ready yet
    if resp.status_code in (401, 403):
        resp.raise_for_status()
    if not resp.is_success:
        return None
    data = resp.json()
    if data.get("status") != "reported":
        return None
    return _normalise(data)


def _normalise(data: dict) -> SandboxReport:
    sigs = data.get("signatures", [])
    techniques = [s["ttp"] for s in sigs if s.get("ttp")]
    network = data.get("network", {})
    iocs = (
        [h["ip"] for h in network.get("hosts", [])]
        + [d["domain"] for d in network.get("domains", [])]
    )
    score = int(data.get("info", {}).get("score", 0))
    verdict = "malicious" if score >= 70 else "suspicious" if score >= 30 else "clean"
    return SandboxReport(
        techniques=techniques,
        network_iocs=iocs,
        process_tree=data.get("processes", {}),
        score=score,
        verdict=verdict,
        raw_json=data,
    )
