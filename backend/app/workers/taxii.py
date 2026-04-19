"""TAXII/STIX polling actor — INGT-01, INGT-02, INGT-03, INGT-04.

- Version negotiation: try taxii2client.v21 first; on failure fall back to v20.
- Pagination: call collection.get_objects(added_after=cursor, next=None) then
 loop while envelope.get("more") is truthy, passing envelope["next"].
- Cursor advance: ONLY after all pages committed. Cursor source
 per TAXII-SPIKE.md recommendation — default = max(modified) across batch.
- Auth: decrypt credentials_enc per poll, inject into Server constructor.
- OTX dispatch: if source URL contains /taxii/discovery and server responds
 with application/xml (TAXII 1.1), route to taxii1_otx.poll_otx_taxii1.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

import dramatiq
from sqlalchemy import create_engine, text, update
from sqlalchemy.orm import Session
from taxii2client.v20 import Server as _taxii_v20_Server_real
from taxii2client.v21 import Server as _taxii_v21_Server_real

from app.crypto import decrypt_credentials
from app.ingest.normalise import _persist_event, update_source_health
from app.services.source_health import update_silent_failure_count
from app.ingest.taxii_parser import normalise_stix_object, parse_stix_bundle
from app.models.markings import TlpMarking
from app.models.sources import Source

logger = logging.getLogger(__name__)

# Exposed as module attributes so tests can monkeypatch
taxii_v21_Server = _taxii_v21_Server_real
taxii_v20_Server = _taxii_v20_Server_real


@contextmanager
def _open_session() -> Iterator[Session]:
    from app.config import settings  # noqa: PLC0415
    sync_url = settings.DATABASE_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url, future=True)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def _fetch_source_row(session: Session, source_id: uuid.UUID) -> dict | None:
    row = session.execute(
        text("SELECT id, url, credentials_enc, last_cursor FROM sources WHERE id = :id"),
        {"id": str(source_id)},
    ).one_or_none()
    if row is None:
        return None
    return {
        "id": row.id, "url": row.url,
        "credentials_enc": row.credentials_enc,
        "last_cursor": row.last_cursor,
    }


def _load_tlp_cache(session: Session) -> dict[uuid.UUID, str]:
    rows = session.execute(
        text("SELECT id, name FROM tlp_markings")
    ).all()
    return {r.id: r.name for r in rows}


def _decrypt_taxii_creds(credentials_enc: str | None) -> dict | None:
    if not credentials_enc:
        return None
    from app.config import settings  # noqa: PLC0415
    try:
        return decrypt_credentials(settings.SECRET_KEY, credentials_enc)
    except Exception as e:  # noqa: BLE001
        logger.warning("taxii_credentials_decrypt_failed error=%s", e)
        return None


def _build_server(url: str, creds: dict | None) -> Any:
    """Version negotiation — prefer v2.1, fall back to v2.0.

 creds shape: {"type":"basic","username":"...","password":"..."} or
 {"type":"bearer","token":"..."} or None.
"""
    # Build auth kwargs
    kwargs: dict = {}
    if creds:
        t = creds.get("type")
        if t == "basic":
            kwargs["user"] = creds.get("username")
            kwargs["password"] = creds.get("password")
        elif t == "bearer":
            # taxii2-client accepts a requests.auth.AuthBase subclass via auth=
            import requests  # noqa: PLC0415
            class _Bearer(requests.auth.AuthBase):
                def __init__(self, tok: str) -> None:
                    self.tok = tok
                def __call__(self, r):  # type: ignore[no-untyped-def]
                    r.headers["Authorization"] = f"Bearer {self.tok}"
                    return r
            kwargs["auth"] = _Bearer(creds.get("token", ""))
    try:
        return taxii_v21_Server(url, **kwargs)
    except Exception as e:  # noqa: BLE001
        logger.warning("taxii_v21_failed url=%s error=%s — falling back to v20", url, e)
        return taxii_v20_Server(url, **kwargs)


def _advance_cursor(session: Session, source_id: uuid.UUID, cursor_iso: str) -> None:
    session.execute(
        update(Source).where(Source.id == source_id).values(last_cursor=cursor_iso)
    )


def _iter_pages(collection: Any, added_after: str | None) -> Iterator[dict]:
    """Yield one envelope per page, walking `more`/`next` pagination."""
    kwargs: dict[str, Any] = {}
    if added_after:
        kwargs["added_after"] = added_after
    envelope = collection.get_objects(**kwargs)
    yield envelope
    while isinstance(envelope, dict) and envelope.get("more"):
        next_tok = envelope.get("next")
        if not next_tok:
            break
        kwargs["next"] = next_tok
        envelope = collection.get_objects(**kwargs)
        yield envelope


def _is_otx_taxii1_source(url: str) -> bool:
    """Heuristic: if the URL contains /taxii/discovery this is an OTX TAXII 1.1 endpoint."""
    return "/taxii/discovery" in url


def poll_taxii_impl(source_id_str: str) -> None:
    source_id = uuid.UUID(source_id_str)
    with _open_session() as session:
        src = _fetch_source_row(session, source_id)
        if src is None:
            logger.error("taxii_poll_source_missing source_id=%s", source_id)
            return
        tlp_cache = _load_tlp_cache(session)
        creds = _decrypt_taxii_creds(src["credentials_enc"])

        # Dispatch to OTX TAXII 1.1 path when URL heuristic matches
        if _is_otx_taxii1_source(src["url"]):
            from app.ingest.taxii1_otx import poll_otx_taxii1  # noqa: PLC0415
            poll_otx_taxii1(session, src, creds, tlp_cache)
            return

        # TAXII 2.1 / 2.0 path
        try:
            server = _build_server(src["url"], creds)
        except Exception as e:  # noqa: BLE001
            logger.warning("taxii_poll_server_init_failed source_id=%s error=%s",
                           source_id, e)
            update_source_health(session, source_id, status="http_error",
                                 succeeded=False)
            session.commit()
            return

        collected_objects: list[Any] = []
        try:
            for api_root in getattr(server, "api_roots", []):
                for collection in getattr(api_root, "collections", []):
                    for envelope in _iter_pages(collection, src["last_cursor"]):
                        objs = envelope.get("objects") if isinstance(envelope, dict) else list(envelope)
                        if objs:
                            collected_objects.extend(objs)
        except Exception as e:  # noqa: BLE001
            logger.warning("taxii_poll_network_error source_id=%s error=%s",
                           source_id, e)
            update_source_health(session, source_id, status="network_error",
                                 succeeded=False)
            session.commit()
            return

        # Parse + persist — on parse failure, drop the single object but keep going.
        inserted = 0
        latest_modified_str: str | None = None
        for obj in collected_objects:
            try:
                parsed_list = parse_stix_bundle([obj])
            except Exception as e:  # noqa: BLE001
                logger.warning("taxii_stix_parse_failed source_id=%s error=%s "
                               "raw=%s", source_id, e, str(obj)[:200])
                continue
            for p in parsed_list:
                row = normalise_stix_object(p, source_id, tlp_cache)
                if row is None:
                    continue
                rc = _persist_event(session, row)
                if rc == 1:
                    inserted += 1
                mod_field = row["raw_stix"].get("modified") or row["raw_stix"].get("created")
                if mod_field and (latest_modified_str is None or str(mod_field) > latest_modified_str):
                    latest_modified_str = str(mod_field)

        # Cursor advance — ONLY after all pages written.
        if latest_modified_str:
            _advance_cursor(session, source_id, latest_modified_str)

        update_source_health(session, source_id, status="ok", succeeded=True)
        update_silent_failure_count(session, source_id, inserted)
        session.commit()
        logger.info("taxii_poll_ok source_id=%s inserted=%d", source_id, inserted)


@dramatiq.actor(max_retries=0, queue_name="ingest")
def poll_taxii(source_id: str) -> None:
    poll_taxii_impl(source_id)
