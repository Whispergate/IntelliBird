"""NVD/CVE polling actor — INGC-01, INGC-02, INGC-03.

Cursor strategy:
 - last_cursor IS NULL → fetch last 30 days.
 - Otherwise → lastModStartDate = last_cursor + 1 second.
 - On success, advance last_cursor to (max lastModified seen) + 1 second.
 - On any failure, cursor is NOT advanced — re-poll covers the same window.

Rate-limit handling:
 - 429 or 5xx: exponential backoff 30s → 60s → 120s (max 3 attempts).
 - After final failure: last_status='rate_limited' (429) or 'http_error' (5xx).
 - Other 4xx: fail fast — no retry, last_status='http_error'.

Event → cve_details / attack_technique_tags linkage:
 - Uses RETURNING id on the events insert to capture the server-generated UUID.
 - ON CONFLICT (source_id, content_hash, observed_at) DO NOTHING matches the
 3-column unique index from migration 002 (required by TimescaleDB hypertable).
 - Dependent writes (cve_details, attack_technique_tags) are skipped when the
 event row is a dedup conflict — they already exist from the original insert.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import dramatiq
import nvdlib
from sqlalchemy import create_engine, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.crypto import decrypt_credentials
from app.ingest.normalise import _persist_event, update_source_health  # noqa: F401 — exposed for monkeypatching
from app.services.source_health import update_silent_failure_count
from app.ingest.nvd_parser import normalise_cve
from app.models.cve_details import CveDetails
from app.models.events import Event
from app.models.sources import Source
from app.models.tags import AttackTechniqueTag

logger = logging.getLogger(__name__)

BACKOFF_SCHEDULE: tuple[int, int, int] = (30, 60, 120)


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
        text("SELECT id, credentials_enc, last_cursor FROM sources WHERE id = :id"),
        {"id": str(source_id)},
    ).one_or_none()
    if row is None:
        return None
    return {
        "id": row.id,
        "credentials_enc": row.credentials_enc,
        "last_cursor": row.last_cursor,
    }


def _decrypt_api_key(credentials_enc: str | None) -> str | None:
    if not credentials_enc:
        return None
    from app.config import settings  # noqa: PLC0415
    try:
        creds = decrypt_credentials(settings.SECRET_KEY, credentials_enc)
    except Exception as e:  # noqa: BLE001
        logger.warning("nvd_credentials_decrypt_failed error=%s", e)
        return None
    if creds.get("type") == "apiKey":
        return creds.get("key")
    return None


def _compute_start(last_cursor: str | None) -> datetime:
    if last_cursor:
        base = datetime.fromisoformat(last_cursor.replace("Z", "+00:00"))
        return base + timedelta(seconds=1)
    return datetime.now(timezone.utc) - timedelta(days=30)


def _write_cve_details(session: Session, event_id: uuid.UUID, row: dict) -> None:
    """Idempotent insert keyed on event_id — skip silently if already present."""
    stmt = pg_insert(CveDetails.__table__).values(event_id=event_id, **row)
    stmt = stmt.on_conflict_do_nothing(index_elements=["event_id"])
    session.execute(stmt)


def _write_attack_tag(session: Session, event_id: uuid.UUID, technique_id: str,
                      url: str) -> None:
    session.execute(
        pg_insert(AttackTechniqueTag.__table__).values(
            event_id=event_id,
            technique_id=technique_id,
            tag_source="feed_asserted",
            evidence_text=url,
        )
    )


def _advance_cursor(session: Session, source_id: uuid.UUID, cursor_iso: str) -> None:
    session.execute(
        update(Source).where(Source.id == source_id).values(last_cursor=cursor_iso)
    )


def _error_status_code(err: BaseException) -> int | None:
    """Extract HTTP status code from nvdlib-shaped exceptions."""
    for attr in ("status_code", "code", "status"):
        v = getattr(err, attr, None)
        if isinstance(v, int):
            return v
    return None


def _fetch_with_backoff(**kwargs: Any) -> list:
    """Call nvdlib.searchCVE_V2 with backoff.

 Returns list of CVE objects on success, or raises the final exception.

 Backoff schedule: sleep 30s, 60s, 120s — one sleep per failed attempt
 (3 attempts total, 3 sleeps). 4xx non-429 fails fast without sleeping.
"""
    last_exc: BaseException | None = None
    for attempt_idx, sleep_s in enumerate(BACKOFF_SCHEDULE):
        try:
            return list(nvdlib.searchCVE_V2(**kwargs))
        except BaseException as e:  # noqa: BLE001
            code = _error_status_code(e)
            last_exc = e
            # 4xx non-429: fail fast — no sleep, propagate immediately
            if code is not None and 400 <= code < 500 and code != 429:
                raise
            # 429 or 5xx: sleep then retry (or give up after last attempt)
            logger.warning(
                "nvd_poll_backoff attempt=%d sleep=%d error=%s",
                attempt_idx + 1, sleep_s, e,
            )
            time.sleep(sleep_s)
    assert last_exc is not None
    raise last_exc


def poll_nvd_impl(source_id_str: str) -> None:
    source_id = uuid.UUID(source_id_str)
    with _open_session() as session:
        src = _fetch_source_row(session, source_id)
        if src is None:
            logger.error("nvd_poll_source_missing source_id=%s", source_id)
            return

        api_key = _decrypt_api_key(src["credentials_enc"])
        start_dt = _compute_start(src["last_cursor"])
        kwargs: dict[str, Any] = {
            "lastModStartDate": start_dt.isoformat(),
            "key": api_key,
        }

        try:
            cves = _fetch_with_backoff(**kwargs)
        except BaseException as e:  # noqa: BLE001
            code = _error_status_code(e)
            if code == 429:
                status = "rate_limited"
            elif code is not None and (500 <= code < 600 or (400 <= code < 500 and code != 429)):
                status = "http_error"
            else:
                status = "network_error"
            logger.warning(
                "nvd_poll_failed source_id=%s status=%s error=%s",
                source_id, status, e,
            )
            update_source_health(session, source_id, status=status, succeeded=False)
            session.commit()
            return

        inserted = 0
        latest_mod: datetime | None = None
        attack_written = 0

        for cve in cves:
            result = normalise_cve(cve, source_id)
            if result is None:
                logger.warning(
                    "feed_item_rejected reason=missing_dedup_key source_id=%s",
                    source_id,
                )
                continue
            event_row, cve_details_row, attack_links = result

            # Insert the event row with RETURNING id so we can link child rows.
            # ON CONFLICT (source_id, content_hash, observed_at) DO NOTHING matches
            # the 3-column unique index from migration 002 (TimescaleDB hypertable).
            stmt = (
                pg_insert(Event.__table__)
                .values(**event_row)
                .on_conflict_do_nothing(
                    index_elements=["source_id", "content_hash", "observed_at"]
                )
                .returning(Event.__table__.c.id)
            )
            result_row = session.execute(stmt).fetchone()
            if result_row is None:
                # Conflict — row already exists; child rows already exist too.
                continue
            event_id = result_row[0]
            inserted += 1

            _write_cve_details(session, event_id, cve_details_row)
            for technique_id, url in attack_links:
                _write_attack_tag(session, event_id, technique_id, url)
                attack_written += 1

            last_mod_dt = cve_details_row.get("last_modified")
            if last_mod_dt is not None and (latest_mod is None or last_mod_dt > latest_mod):
                latest_mod = last_mod_dt

        if latest_mod is not None:
            cursor_iso = (latest_mod + timedelta(seconds=1)).isoformat()
            _advance_cursor(session, source_id, cursor_iso)

        update_source_health(session, source_id, status="ok", succeeded=True)
        update_silent_failure_count(session, source_id, inserted)
        session.commit()
        logger.info(
            "nvd_poll_ok source_id=%s inserted=%d attack_tags=%d",
            source_id, inserted, attack_written,
        )


@dramatiq.actor(max_retries=0, queue_name="ingest")
def poll_nvd(source_id: str) -> None:
    poll_nvd_impl(source_id)
