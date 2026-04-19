
"""OTX-specific TAXII 1.1 XML poller (Scope-C, hand-rolled).

AlienVault OTX speaks TAXII 1.1 XML — not TAXII 2.1 JSON. The taxii2-client
library cannot communicate with it. This module hand-rolls the three required
TAXII 1.1 messages:
 1. Discovery_Request → Discovery_Response (locate poll service URL)
 2. Collection_Information_Request → Collection_Information_Response (list collections)
 3. Poll_Request (with Exclusive_Begin_Timestamp cursor) → Poll_Response

Auth: X-OTX-API-KEY header injected from credentials_enc {"type": "otx-apikey", "key": "..."}.

Parse path: Poll_Response Content_Block elements contain STIX 2.x or STIX 1.x XML
payloads. STIX 2.x JSON-in-XML is extracted and routed through normalise_stix_object.
STIX 1.x XML objects are stored as raw JSONB with synthesized stix_type="x-stix1-*".

NOTE: This is OTX-specific. Not a general TAXII 1.1 implementation. Brittle to
OTX server changes. Revisit with pymisp MISP adapter in M3. (Scope-C, TAXII-SPIKE.md)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# TAXII 1.1 XML namespaces
_TAXII_11_NS = "http://taxii.mitre.org/messages/taxii_xml_binding-1.1"
_NS = {"taxii_11": _TAXII_11_NS}

# TAXII 1.1 required headers for all messages
_TAXII_11_HEADERS = {
    "Accept": "application/xml",
    "Content-Type": "application/xml",
    "X-TAXII-Accept": "urn:taxii.mitre.org:message:xml:1.1",
    "X-TAXII-Content-Type": "urn:taxii.mitre.org:message:xml:1.1",
    "X-TAXII-Protocol": "urn:taxii.mitre.org:protocol:https:1.0",
    "X-TAXII-Services": "urn:taxii.mitre.org:services:1.1",
}

_DISCOVERY_REQUEST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<taxii_11:Discovery_Request
 xmlns:taxii_11="{ns}"
 message_id="1"/>
""".format(ns=_TAXII_11_NS)

_COLLECTION_REQUEST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<taxii_11:Collection_Information_Request
 xmlns:taxii_11="{ns}"
 message_id="2"/>
""".format(ns=_TAXII_11_NS)


def _poll_request_xml(collection_name: str, begin_ts: str | None) -> str:
    """Build a TAXII 1.1 Poll_Request XML string.

 begin_ts: ISO 8601 UTC timestamp for Exclusive_Begin_Timestamp, or None.
"""
    begin_elem = ""
    if begin_ts:
        begin_elem = f"""
 <taxii_11:Exclusive_Begin_Timestamp>{begin_ts}</taxii_11:Exclusive_Begin_Timestamp>"""
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<taxii_11:Poll_Request
 xmlns:taxii_11="{_TAXII_11_NS}"
 message_id="3"
 collection_name="{collection_name}">{begin_elem}
 <taxii_11:Poll_Parameters allow_asynch="false">
 <taxii_11:Response_Type>FULL</taxii_11:Response_Type>
 </taxii_11:Poll_Parameters>
</taxii_11:Poll_Request>"""


def _make_otx_session(api_key: str) -> Any:
    """Return a requests.Session pre-loaded with OTX + TAXII 1.1 headers."""
    import requests  # noqa: PLC0415
    sess = requests.Session()
    sess.headers.update(_TAXII_11_HEADERS)
    sess.headers["X-OTX-API-KEY"] = api_key
    return sess


def _discover_services(session: Any, discovery_url: str) -> dict[str, str]:
    """POST Discovery_Request → extract service addresses from Discovery_Response.

 Returns dict keyed by service type (lowercase) → address URL.
 e.g. {"discovery": "...", "collection-management": "...", "poll": "..."}
"""
    try:
        from lxml import etree  # noqa: PLC0415
    except ImportError as e:
        raise RuntimeError("lxml is required for TAXII 1.1 parsing") from e

    resp = session.post(discovery_url, data=_DISCOVERY_REQUEST_TEMPLATE, timeout=30)
    resp.raise_for_status()
    root = etree.fromstring(resp.content)
    services: dict[str, str] = {}
    for svc in root.findall("taxii_11:Service_Instance", _NS):
        svc_type = (svc.get("service_type") or "").lower()
        addr_el = svc.find("taxii_11:Address", _NS)
        if addr_el is not None and addr_el.text:
            services[svc_type] = addr_el.text.strip()
    logger.info("otx_taxii1_discovered services=%s", list(services.keys()))
    return services


def _list_collections(session: Any, collection_url: str) -> list[str]:
    """POST Collection_Information_Request → return list of collection names."""
    try:
        from lxml import etree  # noqa: PLC0415
    except ImportError as e:
        raise RuntimeError("lxml is required for TAXII 1.1 parsing") from e

    resp = session.post(collection_url, data=_COLLECTION_REQUEST_TEMPLATE, timeout=30)
    resp.raise_for_status()
    root = etree.fromstring(resp.content)
    names: list[str] = []
    for coll in root.findall("taxii_11:Collection", _NS):
        name = coll.get("collection_name")
        if name:
            names.append(name)
    logger.info("otx_taxii1_collections count=%d names=%s", len(names), names[:5])
    return names


def _poll_collection(
    session: Any,
    poll_url: str,
    collection_name: str,
    begin_ts: str | None,
) -> list[dict]:
    """POST Poll_Request → extract Content_Block payloads → return list of raw dicts.

 Each returned dict has at least: 'type', 'id' (synthesized if STIX 1.x).
"""
    try:
        from lxml import etree  # noqa: PLC0415
    except ImportError as e:
        raise RuntimeError("lxml is required for TAXII 1.1 parsing") from e

    xml_body = _poll_request_xml(collection_name, begin_ts)
    resp = session.post(poll_url, data=xml_body, timeout=60)
    resp.raise_for_status()
    root = etree.fromstring(resp.content)

    objects: list[dict] = []
    for block in root.findall("taxii_11:Content_Block", _NS):
        content_el = block.find("taxii_11:Content", _NS)
        if content_el is None:
            continue
        # Try JSON content first (STIX 2.x embedded in XML Content element)
        text_content = (content_el.text or "").strip()
        if text_content.startswith("{"):
            import json  # noqa: PLC0415
            try:
                obj = json.loads(text_content)
                if isinstance(obj, dict):
                    objects.append(obj)
                elif isinstance(obj, list):
                    objects.extend(obj)
                continue
            except Exception:  # noqa: BLE001
                pass

        # Try child XML elements (STIX 1.x or STIX 2.x JSON-in-XML)
        for child in content_el:
            # Check for STIX 2.x JSON content nested in an inner XML element
            child_text = (child.text or "").strip()
            if child_text.startswith("{"):
                import json  # noqa: PLC0415
                try:
                    obj = json.loads(child_text)
                    if isinstance(obj, dict):
                        objects.append(obj)
                    continue
                except Exception:  # noqa: BLE001
                    pass
            # STIX 1.x XML — synthesize a STIX 2.x-compatible dict. Extract
            # Title + Description from STIX_Header for operator-visible fields.
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            obj_id = child.get("id") or f"x-stix1-{tag}--{uuid.uuid4()}"
            now_iso = datetime.now(timezone.utc).isoformat()

            # Extract Title + Description via local-name XPath (stix namespace varies)
            title_text: str | None = None
            desc_text: str | None = None
            for t in child.xpath(
                ".//*[local-name()='STIX_Header']/*[local-name()='Title']"
            ):
                if t.text:
                    title_text = t.text.strip()
                    break
            for d in child.xpath(
                ".//*[local-name()='STIX_Header']/*[local-name()='Description']"
            ):
                if d.text:
                    desc_text = d.text.strip()
                    break

            # Fallbacks
            if not title_text:
                title_text = f"OTX Pulse ({tag})"
            labels = ["otx", "stix1"]

            objects.append({
                "type": f"x-stix1-{tag.lower()}",
                "id": obj_id,
                "spec_version": "2.1",
                "created": now_iso,
                "modified": now_iso,
                "name": title_text,
                "description": desc_text or "",
                "labels": labels,
                "raw_xml": etree.tostring(child, encoding="unicode"),
            })

    logger.info("otx_taxii1_polled collection=%s objects=%d", collection_name, len(objects))
    return objects


def poll_otx_taxii1(
    session: Any,
    src: dict,
    creds: dict | None,
    tlp_cache: dict[uuid.UUID, str],
) -> None:
    """OTX TAXII 1.1 poll entry point — called by taxii.poll_taxii_impl when
 the URL heuristic matches /taxii/discovery.

 Performs Discovery → Collections → Poll → normalise → persist → cursor advance.
 Cursor advance ONLY after all objects committed.
"""
    from app.ingest.normalise import _persist_event, update_source_health  # noqa: PLC0415
    from app.ingest.taxii_parser import normalise_stix_object  # noqa: PLC0415
    from sqlalchemy import update as sa_update  # noqa: PLC0415
    from app.models.sources import Source  # noqa: PLC0415

    source_id: uuid.UUID = src["id"] if isinstance(src["id"], uuid.UUID) else uuid.UUID(str(src["id"]))
    discovery_url: str = src["url"]

    # Extract API key
    api_key: str | None = None
    if creds and creds.get("type") == "otx-apikey":
        api_key = creds.get("key")
    if not api_key:
        logger.warning("otx_taxii1_no_api_key source_id=%s", source_id)
        update_source_health(session, source_id, status="http_error", succeeded=False)
        session.commit()
        return

    otx_session = _make_otx_session(api_key)

    try:
        services = _discover_services(otx_session, discovery_url)
    except Exception as e:  # noqa: BLE001
        logger.warning("otx_taxii1_discovery_failed source_id=%s error=%s", source_id, e)
        update_source_health(session, source_id, status="network_error", succeeded=False)
        session.commit()
        return

    # Locate poll service URL. OTX discovery returns service_type in the form
    # `COLLECTION_MANAGEMENT` / `POLL` — lowercased earlier → `collection_management`.
    poll_url = services.get("poll")
    collection_url = (
        services.get("collection_management")
        or services.get("collection-management")  # legacy fallback
        or services.get("collections")
    )
    if not poll_url:
        logger.warning("otx_taxii1_no_poll_service source_id=%s services=%s",
                       source_id, list(services.keys()))
        update_source_health(session, source_id, status="http_error", succeeded=False)
        session.commit()
        return

    # List collections
    if collection_url:
        try:
            collection_names = _list_collections(otx_session, collection_url)
        except Exception as e:  # noqa: BLE001
            logger.warning("otx_taxii1_list_collections_failed source_id=%s error=%s",
                           source_id, e)
            collection_names = []
    else:
        collection_names = []

    if not collection_names:
        # Fall back to a known OTX default collection name
        collection_names = ["AlienVault OTX Pulse"]
        logger.info("otx_taxii1_fallback_collection source_id=%s", source_id)

    cursor = src.get("last_cursor")
    all_objects: list[dict] = []

    for coll_name in collection_names:
        try:
            objects = _poll_collection(otx_session, poll_url, coll_name, cursor)
            all_objects.extend(objects)
        except Exception as e:  # noqa: BLE001
            logger.warning("otx_taxii1_poll_failed source_id=%s collection=%s error=%s",
                           source_id, coll_name, e)
            update_source_health(session, source_id, status="network_error", succeeded=False)
            session.commit()
            return

    # Normalise + persist (all objects, then advance cursor —)
    inserted = 0
    latest_modified_str: str | None = None

    for obj in all_objects:
        if obj.get("type") == "bundle" and "objects" in obj:
            # Unwrap STIX 2 bundles embedded in OTX responses
            items = obj["objects"]
        else:
            items = [obj]

        for item in items:
            row = normalise_stix_object(item, source_id, tlp_cache)
            if row is None:
                continue
            rc = _persist_event(session, row)
            if rc == 1:
                inserted += 1
            mod_field = row["raw_stix"].get("modified") or row["raw_stix"].get("created")
            if mod_field and (latest_modified_str is None or str(mod_field) > latest_modified_str):
                latest_modified_str = str(mod_field)

    # Cursor advance ONLY after all persists complete
    if latest_modified_str:
        session.execute(
            sa_update(Source).where(Source.id == source_id).values(last_cursor=latest_modified_str)
        )

    update_source_health(session, source_id, status="ok", succeeded=True)
    session.commit()
    logger.info("otx_taxii1_poll_ok source_id=%s inserted=%d", source_id, inserted)
