#!/usr/bin/env python3
"""TAXII compatibility spike for IntelliBird.

Runs against MITRE CTI, AlienVault OTX, and CIRCL OSINT. Prints
per-server findings to stdout in a TAXII-SPIKE.md-ready format.

Usage:
 cd backend && uv run python scripts/taxii_spike.py [--mitre] [--otx] [--circl] [--all]

Env vars:
 OTX_API_KEY -- AlienVault OTX API key (required for OTX section;
 if unset, OTX section is marked "skipped: no API key").
 CIRCL_TOKEN -- optional bearer token for CIRCL if the operator has one.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import traceback
from typing import Any

try:
    from taxii2client import v20 as taxii_v20
    from taxii2client import v21 as taxii_v21
except ImportError:
    print(
        "FATAL: taxii2-client is not installed. Run `uv sync` in backend/.",
        file=sys.stderr,
    )
    sys.exit(2)

try:
    import httpx
except ImportError:
    print(
        "FATAL: httpx is not installed. Run `uv sync` in backend/.",
        file=sys.stderr,
    )
    sys.exit(2)


TARGETS: dict[str, dict[str, Any]] = {
    "mitre": {
        "name": "MITRE CTI (ATT&CK)",
        # /taxii2/ is the TAXII 2.1 discovery endpoint (returns api_roots).
        # /api/v21/ is the API root itself -- using it as the Server URL
        # results in zero api_roots because taxii2client expects a discovery URL.
        "urls": [
            "https://attack-taxii.mitre.org/taxii2/",
            "https://attack-taxii.mitre.org/api/v21/",
        ],
        "auth": None,
    },
    "otx": {
        "name": "AlienVault OTX",
        "urls": [
            "https://otx.alienvault.com/taxii2/",
            "https://otx.alienvault.com/taxii/",
        ],
        "auth": "apikey-env:OTX_API_KEY",
    },
    "circl": {
        "name": "CIRCL OSINT (MISP)",
        "urls": [
            "https://misppriv.circl.lu/taxii2/",
            "https://www.circl.lu/doc/misp/taxii/",
            "https://taxii.circl.lu/",
        ],
        "auth": "bearer-env:CIRCL_TOKEN",
    },
}


def _probe_version(
    url: str, *, auth_kwargs: dict | None = None
) -> tuple[str | None, str]:
    """Return (version, note) where version is '2.1', '2.0', or None."""
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            headers = {"Accept": "application/taxii+json;version=2.1"}
            auth = auth_kwargs.get("http_auth") if auth_kwargs else None
            resp = client.get(url, headers=headers, auth=auth)
            ct = resp.headers.get("content-type", "").lower()
            if "version=2.1" in ct:
                return "2.1", f"HTTP {resp.status_code}; Content-Type: {ct}"
            if "version=2.0" in ct:
                return "2.0", f"HTTP {resp.status_code}; Content-Type: {ct}"
            return (
                None,
                f"HTTP {resp.status_code}; Content-Type: {ct}; "
                f"body[:200]={resp.text[:200]!r}",
            )
    except Exception as e:  # noqa: BLE001
        return None, f"probe-failed: {e}"


def _probe_server(target_key: str) -> dict[str, Any]:
    """Return a findings dict for one target. Never raises."""
    target = TARGETS[target_key]
    findings: dict[str, Any] = {
        "target": target["name"],
        "urls_tried": [],
        "version": None,
        "api_roots": [],
        "auth_scheme": None,
        "collection_sampled": None,
        "first_page_object_count": None,
        "x_taxii_date_added_last": None,
        "envelope_has_more": None,
        "envelope_has_next": None,
        "first_object_added": None,
        "added_after_filtered_count": None,
        "added_after_behavior": None,  # "filters" | "ignores-filter" | "unknown"
        "errors": [],
        "notes": [],
    }

    # ---------- Resolve auth ----------
    auth_kwargs: dict[str, Any] = {}
    auth_marker = target.get("auth") or ""

    if auth_marker.startswith("apikey-env:"):
        var = auth_marker.split(":", 1)[1]
        key = os.environ.get(var)
        if not key:
            findings["notes"].append(f"skipped: no API key (set {var})")
            return findings
        findings["auth_scheme"] = (
            f"header X-OTX-API-KEY (via requests.Session hook, env {var})"
        )
        auth_kwargs = {"otx_api_key": key}

    elif auth_marker.startswith("bearer-env:"):
        var = auth_marker.split(":", 1)[1]
        tok = os.environ.get(var)
        if tok:
            findings["auth_scheme"] = f"bearer token via env {var}"
            auth_kwargs = {"bearer": tok}
        else:
            findings["notes"].append(
                f"attempting unauthenticated; set {var} to test bearer path"
            )

    # ---------- Probe each URL in priority order ----------
    for url in target["urls"]:
        findings["urls_tried"].append(url)
        version, note = _probe_version(url)
        findings["notes"].append(f"{url} -> {note}")
        if version is None:
            continue
        findings["version"] = version

        # ---- Try taxii2-client negotiation ----
        try:
            ServerCls = taxii_v21.Server if version == "2.1" else taxii_v20.Server

            client_kwargs: dict[str, Any] = {}

            if auth_kwargs.get("otx_api_key"):
                # OTX accepts the key as X-OTX-API-KEY header.
                # taxii2-client 2.3.0 supports a `session=` kwarg (requests.Session).
                import requests  # noqa: PLC0415

                sess = requests.Session()
                sess.headers.update({"X-OTX-API-KEY": auth_kwargs["otx_api_key"]})
                client_kwargs["session"] = sess
                findings["notes"].append(
                    "taxii2client kwarg used: session=requests.Session() "
                    "with X-OTX-API-KEY header"
                )

            elif auth_kwargs.get("bearer"):
                # Test whether taxii2-client accepts a bearer token via `auth=`
                import requests  # noqa: PLC0415
                import requests.auth  # noqa: PLC0415

                class _BearerAuth(requests.auth.AuthBase):
                    def __init__(self, tok: str) -> None:
                        self.tok = tok

                    def __call__(self, r: Any) -> Any:
                        r.headers["Authorization"] = f"Bearer {self.tok}"
                        return r

                client_kwargs["auth"] = _BearerAuth(auth_kwargs["bearer"])
                findings["notes"].append(
                    "taxii2client kwarg used: auth=_BearerAuth(token) "
                    "(requests.auth.AuthBase subclass)"
                )

            server = ServerCls(url, **client_kwargs)
            api_roots = list(server.api_roots)
            findings["api_roots"] = [str(ar.url) for ar in api_roots]

            if not api_roots:
                findings["errors"].append("no api_roots discovered")
                break

            # Pick the first populated collection
            picked = None
            for ar in api_roots:
                try:
                    for c in ar.collections:
                        picked = c
                        break
                except Exception as e:  # noqa: BLE001
                    findings["notes"].append(
                        f"collection list failed for api_root {ar.url}: {e}"
                    )
                if picked:
                    break

            if not picked:
                findings["errors"].append(
                    "no collections discovered (all api_roots failed or empty)"
                )
                break

            findings["collection_sampled"] = str(picked.url)

            # ---- Unfiltered first page ----
            env = picked.get_objects()
            objs: list[dict] = []
            if isinstance(env, dict):
                objs = list(env.get("objects") or [])
            else:
                # Some versions return a generator-like object
                try:
                    objs = list(env)
                except Exception:  # noqa: BLE001
                    objs = []

            findings["first_page_object_count"] = len(objs)

            # X-TAXII-Date-Added-Last -- taxii2-client does NOT expose this header
            # via the envelope dict. Fall back to a direct HTTP probe using httpx
            # against the collections/objects/ endpoint to capture the raw header.
            last_header: str | None = None
            if isinstance(env, dict):
                last_header = env.get("_headers", {}).get("X-TAXII-Date-Added-Last")
            if last_header is None:
                raw_resp = getattr(env, "_raw_response", None) or getattr(
                    env, "raw_response", None
                )
                if raw_resp is not None:
                    last_header = getattr(raw_resp, "headers", {}).get(
                        "X-TAXII-Date-Added-Last"
                    )
            # Direct HTTP fallback: probe the collection objects endpoint with httpx
            if last_header is None and picked is not None:
                try:
                    _obj_url = str(picked.url).rstrip("/") + "/objects/"
                    _http_headers = {"Accept": "application/taxii+json;version=2.1"}
                    with httpx.Client(timeout=15.0, follow_redirects=True) as _hc:
                        _hr = _hc.get(
                            _obj_url,
                            headers=_http_headers,
                            params={"limit": 1},
                        )
                        last_header = _hr.headers.get("X-TAXII-Date-Added-Last")
                        findings["notes"].append(
                            f"X-TAXII-Date-Added-Last probed via direct HTTP "
                            f"({_obj_url}): {last_header!r}"
                        )
                except Exception as _e:  # noqa: BLE001
                    findings["notes"].append(
                        f"direct HTTP header probe failed: {_e}"
                    )
            findings["x_taxii_date_added_last"] = last_header

            findings["envelope_has_more"] = (
                bool(env.get("more")) if isinstance(env, dict) else None
            )
            findings["envelope_has_next"] = (
                bool(env.get("next")) if isinstance(env, dict) else None
            )

            if objs:
                first_obj = objs[0] if isinstance(objs[0], dict) else vars(objs[0])
                findings["first_object_added"] = first_obj.get(
                    "created"
                ) or first_obj.get("modified")

            # ---- added_after: 30 days ago ----
            thirty_days_ago = (
                dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)
            ).isoformat()
            try:
                env2 = picked.get_objects(added_after=thirty_days_ago)
                objs2: list[dict] = []
                if isinstance(env2, dict):
                    objs2 = list(env2.get("objects") or [])
                else:
                    try:
                        objs2 = list(env2)
                    except Exception:  # noqa: BLE001
                        objs2 = []

                count2 = len(objs2)
                findings["added_after_filtered_count"] = count2
                unfiltered = findings["first_page_object_count"] or 0
                if count2 < unfiltered:
                    findings["added_after_behavior"] = "filters"
                elif count2 == unfiltered:
                    findings["added_after_behavior"] = "ignores-filter"
                else:
                    findings["added_after_behavior"] = "unexpected-more-after-filter"
            except Exception as e:  # noqa: BLE001
                findings["added_after_behavior"] = f"error: {e}"

            # Success - stop trying alternate URLs
            break

        except Exception as e:  # noqa: BLE001
            findings["errors"].append(
                f"{url}: {type(e).__name__}: {e}\n"
                + traceback.format_exc(limit=3)
            )
            continue

    return findings


def _render_markdown_section(key: str, f: dict[str, Any]) -> str:
    lines = [f"## {f['target']} (`{key}`)", ""]

    # Skipped section
    if f["notes"] and any(n.startswith("skipped:") for n in f["notes"]):
        lines.append("**Status:** skipped")
        for n in f["notes"]:
            if n.startswith("skipped:"):
                lines.append(f"**Reason:** {n}")
        lines.append("")
        return "\n".join(lines)

    lines += [
        f"- **TAXII version detected:** {f['version'] or 'unknown'}",
        f"- **URLs tried:** {', '.join(f['urls_tried'])}",
        f"- **Auth scheme used:** {f['auth_scheme'] or 'none (unauthenticated)'}",
        f"- **API roots discovered:** {f['api_roots']}",
        f"- **Sampled collection:** {f['collection_sampled']}",
        f"- **First-page object count (unfiltered):** {f['first_page_object_count']}",
        f"- **X-TAXII-Date-Added-Last header:** {f['x_taxii_date_added_last']}",
        f"- **Envelope has `more`:** {f['envelope_has_more']}",
        f"- **Envelope has `next`:** {f['envelope_has_next']}",
        f"- **First object `created`/`modified`:** {f['first_object_added']}",
        (
            f"- **added_after behavior (30-day window):** "
            f"{f['added_after_behavior']} "
            f"(filtered_count={f['added_after_filtered_count']})"
        ),
    ]

    if f["errors"]:
        lines.append("- **Errors:**")
        for e in f["errors"]:
            lines.append(f"  - `{str(e)[:400]}`")

    if f["notes"]:
        lines.append("- **Notes:**")
        for n in f["notes"]:
            lines.append(f"  - {n}")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="TAXII compatibility spike for IntelliBird."
    )
    parser.add_argument("--mitre", action="store_true", help="Test MITRE CTI server")
    parser.add_argument("--otx", action="store_true", help="Test AlienVault OTX server")
    parser.add_argument("--circl", action="store_true", help="Test CIRCL OSINT server")
    parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Test all three servers (default when no flags given)",
    )
    args = parser.parse_args()

    # If no specific flag is given, default to --all
    any_specific = args.mitre or args.otx or args.circl
    run_all = args.all or not any_specific

    selected: list[str] = []
    if args.mitre or run_all:
        selected.append("mitre")
    if args.otx or run_all:
        selected.append("otx")
    if args.circl or run_all:
        selected.append("circl")

    run_at = dt.datetime.now(dt.timezone.utc).isoformat()
    print("# TAXII Spike Results")
    print()
    print(f"Run at: {run_at}")
    print()

    all_findings: dict[str, Any] = {}
    for key in selected:
        print(f"Probing {TARGETS[key]['name']}...", file=sys.stderr)
        f = _probe_server(key)
        all_findings[key] = f
        print(_render_markdown_section(key, f))

    print("## Raw JSON Output")
    print()
    print("```json")
    print(json.dumps(all_findings, indent=2, default=str))
    print("```")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
