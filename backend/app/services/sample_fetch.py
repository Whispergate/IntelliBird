"""
— Sample fetcher: MalwareBazaar (primary) -> VirusTotal Premium (fallback).
SECURITY: Sample bytes are NEVER written to disk. Caller must use in-memory only.
"""
from __future__ import annotations
import io
import logging
import zipfile
import httpx

log = logging.getLogger(__name__)

_MB_API = "https://mb-api.abuse.ch/api/v1/"
_VT_API = "https://www.virustotal.com/api/v3/files"


async def fetch_sample(
    client: httpx.AsyncClient,
    sha256: str,
    vt_api_key: str | None = None,
) -> bytes | None:
    """
    Fetch sample bytes for SHA256 hash.
    Priority: MalwareBazaar (free, no key) -> VirusTotal Premium (if vt_api_key).
    Returns raw bytes or None if sample is not available.
    NEVER writes to disk.
    """
    sample = await _fetch_malwarebazaar(client, sha256)
    if sample is not None:
        log.info("sample_fetch_ok source=malwarebazaar sha256=%.16s", sha256)
        return sample
    if vt_api_key:
        sample = await _fetch_virustotal(client, sha256, vt_api_key)
        if sample is not None:
            log.info("sample_fetch_ok source=virustotal sha256=%.16s", sha256)
            return sample
    log.info("sample_fetch_miss sha256=%.16s", sha256)
    return None


async def _fetch_malwarebazaar(client: httpx.AsyncClient, sha256: str) -> bytes | None:
    try:
        resp = await client.post(
            _MB_API,
            data={"query": "get_file", "sha256_hash": sha256},
            timeout=30.0,
        )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        log.warning("malwarebazaar_fetch_error sha256=%.16s error=%r", sha256, exc)
        return None
    if resp.status_code != 200:
        return None
    # MalwareBazaar returns JSON {"query_status": "file_not_found"} on miss — NOT a ZIP
    if resp.content[:1] == b"{":
        return None
    try:
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = zf.namelist()
        if not names:
            return None
        return zf.read(names[0], pwd=b"infected")
    except (zipfile.BadZipFile, RuntimeError) as exc:
        log.warning("malwarebazaar_zip_error sha256=%.16s error=%r", sha256, exc)
        return None


async def _fetch_virustotal(client: httpx.AsyncClient, sha256: str, api_key: str) -> bytes | None:
    try:
        resp = await client.get(
            f"{_VT_API}/{sha256}/download",
            headers={"x-apikey": api_key},
            timeout=30.0,
        )
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        log.warning("virustotal_fetch_error sha256=%.16s error=%r", sha256, exc)
        return None
    if resp.status_code == 403:
        log.warning("virustotal_fetch_premium_required sha256=%.16s", sha256)
        return None
    if not resp.is_success:
        return None
    return resp.content
