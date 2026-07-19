"""Synchronous Test Connection probes for SRC-03.

These helpers run in the HTTP request handler path - they must be SHORT,
never touch the DB, never dispatch Dramatiq actors. Return a 4-tuple
(ok, latency_ms, item_count_sampled, error_detail).

Reuses parsers:
 - RSS: app.ingest.rss_parser.parse_rss_feed (HTTP GET + feedparser)
 - NVD: nvdlib.searchCVE_V2 with limit=1
 - TAXII: taxii2client.v21.Server discovery
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def _elapsed_ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _probe_rss(url: str) -> tuple[bool, int, int, str | None]:
    from app.ingest.rss_parser import parse_rss_feed  # noqa: PLC0415

    t0 = time.monotonic()
    try:
        parsed = parse_rss_feed(url)
        elapsed = _elapsed_ms(t0)
        entries = list(getattr(parsed, "entries", []) or [])
        if getattr(parsed, "bozo", 0) and not entries:
            reason = str(getattr(parsed, "bozo_exception", "parse error"))
            return False, elapsed, 0, reason
        return True, elapsed, len(entries), None
    except Exception as e:  # noqa: BLE001
        return False, _elapsed_ms(t0), 0, str(e)


def _probe_nvd(api_key: str | None) -> tuple[bool, int, int, str | None]:
    import nvdlib  # noqa: PLC0415

    t0 = time.monotonic()
    try:
        # Single-record probe - nvdlib returns a generator; materialise up to 1.
        results = list(nvdlib.searchCVE_V2(key=api_key, limit=1))  # type: ignore[attr-defined]
        return True, _elapsed_ms(t0), len(results), None
    except Exception as e:  # noqa: BLE001
        return False, _elapsed_ms(t0), 0, str(e)


def _probe_html_scrape(
    url: str, scrape_config: dict | None
) -> tuple[bool, int, int, str | None]:
    """Quick task 260425-ovt: synchronous probe for feed_type='custom'.

    Validates the scrape_config, fetches the URL with a 10s timeout, runs the
    selectors, and returns (ok, latency_ms, item_count_sampled, error_detail).

    Supports {mode: 'auto'} (quick task 260426-aas) for selectorless probing -
    the underlying ``normalise_scrape_entries`` dispatches to trafilatura-based
    auto-discovery when the mode flag is set.
    """
    from app.ingest.html_scrape_parser import (  # noqa: PLC0415
        fetch_html,
        normalise_scrape_entries,
        validate_scrape_config,
    )
    import uuid as _uuid  # noqa: PLC0415

    t0 = time.monotonic()
    try:
        validate_scrape_config(scrape_config or {})
    except ValueError as e:
        return False, _elapsed_ms(t0), 0, str(e)

    try:
        html_text = fetch_html(url, timeout_sec=10)
    except Exception as e:  # noqa: BLE001
        return False, _elapsed_ms(t0), 0, str(e)

    try:
        # Probe with a placeholder source_id - we never persist these rows.
        rows = normalise_scrape_entries(
            html_text, url, _uuid.UUID("00000000-0000-0000-0000-000000000000"),
            scrape_config or {},
        )
        return True, _elapsed_ms(t0), len(rows), None
    except Exception as e:  # noqa: BLE001
        return False, _elapsed_ms(t0), 0, str(e)


def _probe_taxii(
    url: str, credentials: dict[str, Any] | None
) -> tuple[bool, int, int, str | None]:
    """Probe TAXII endpoint. Routes to 1.1 XML path for OTX (per TAXII-SPIKE.md),
 2.1 path otherwise. Detects OTX by URL heuristic `/taxii/discovery`
 (OTX endpoint shape) or auth type `otx-apikey`.
"""
    t0 = time.monotonic()
    ctype = (credentials or {}).get("type") if credentials else None
    is_otx = "/taxii/discovery" in (url or "") or ctype == "otx-apikey"
    if is_otx:
        return _probe_taxii1_otx(url, credentials, t0)
    return _probe_taxii2(url, credentials, t0)


def _probe_taxii2(
    url: str, credentials: dict[str, Any] | None, t0: float
) -> tuple[bool, int, int, str | None]:
    """TAXII 2.1 via taxii2client - MITRE CTI style."""
    from taxii2client.v21 import Server  # noqa: PLC0415

    kwargs: dict[str, Any] = {}
    if credentials:
        ctype = credentials.get("type")
        if ctype == "basic":
            kwargs["user"] = credentials.get("username", "")
            kwargs["password"] = credentials.get("password", "")
        elif ctype == "bearer":
            token = credentials.get("token") or ""
            kwargs["headers"] = {"Authorization": f"Bearer {token}"}

    try:
        srv = Server(url, **kwargs)
        api_roots = list(getattr(srv, "api_roots", []) or [])
        elapsed = _elapsed_ms(t0)
        if not api_roots:
            return False, elapsed, 0, "no api_roots returned by TAXII discovery"
        return True, elapsed, len(api_roots), None
    except Exception as e:  # noqa: BLE001
        return False, _elapsed_ms(t0), 0, str(e)


def _probe_taxii1_otx(
    url: str, credentials: dict[str, Any] | None, t0: float
) -> tuple[bool, int, int, str | None]:
    """OTX-specific TAXII 1.1 XML discovery probe (per TAXII-SPIKE.md).

 POSTs XML Discovery_Request with X-TAXII-* headers + X-OTX-API-KEY.
 Accepts `credentials.type == "otx-apikey"` with key in `credentials.key`
 (preferred) or `credentials.token`, or `credentials.type == "basic"` with
 password as the key (UI currently ships Basic auth for OTX).
"""
    import requests  # type: ignore[import-untyped]  # noqa: PLC0415

    key = ""
    if credentials:
        ctype = credentials.get("type")
        if ctype == "otx-apikey":
            key = credentials.get("key") or credentials.get("token") or ""
        elif ctype == "basic":
            # Legacy shape - UI defaults to Basic; password IS the OTX API key
            key = credentials.get("password") or credentials.get("key") or ""
        elif ctype == "bearer":
            key = credentials.get("token") or credentials.get("key") or ""

    headers = {
        "Accept": "application/xml",
        "Content-Type": "application/xml",
        "X-TAXII-Accept": "urn:taxii.mitre.org:message:xml:1.1",
        "X-TAXII-Content-Type": "urn:taxii.mitre.org:message:xml:1.1",
        "X-TAXII-Protocol": "urn:taxii.mitre.org:protocol:https:1.0",
        "X-TAXII-Services": "urn:taxii.mitre.org:services:1.1",
    }
    if key:
        headers["X-OTX-API-KEY"] = key

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<taxii_11:Discovery_Request '
        'xmlns:taxii_11="http://taxii.mitre.org/messages/taxii_xml_binding-1.1" '
        'message_id="probe-1"/>'
    )

    try:
        resp = requests.post(url, headers=headers, data=body, timeout=10)
        elapsed = _elapsed_ms(t0)
        if resp.status_code != 200:
            return (
                False,
                elapsed,
                0,
                f"HTTP {resp.status_code} from TAXII 1.1 discovery",
            )
        text = resp.text or ""
        if "Discovery_Response" not in text:
            return False, elapsed, 0, "response missing TAXII 1.1 Discovery_Response"
        # Count Service_Instance tags as a crude service count
        service_count = text.count("Service_Instance")
        return True, elapsed, service_count, None
    except Exception as e:  # noqa: BLE001
        return False, _elapsed_ms(t0), 0, str(e)
