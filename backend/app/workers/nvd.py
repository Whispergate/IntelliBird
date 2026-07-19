"""NVD/CVE polling actor - INGC-01, INGC-02, INGC-03.

Cursor strategy:
 - last_cursor IS NULL → fetch last 30 days.
 - Otherwise → lastModStartDate = last_cursor + 1 second.
 - On success, advance last_cursor to (max lastModified seen) + 1 second.
 - On any failure, cursor is NOT advanced - re-poll covers the same window.

Rate-limit handling:
 - 429 or 5xx: exponential backoff 30s → 60s → 120s (max 3 attempts).
 - After final failure: last_status='rate_limited' (429) or 'http_error' (5xx).
 - Other 4xx: fail fast - no retry, last_status='http_error'.

Event → cve_details / attack_technique_tags linkage:
 - Uses RETURNING id on the events insert to capture the server-generated UUID.
 - ON CONFLICT (source_id, content_hash, observed_at) DO NOTHING matches the
 3-column unique index from migration 002 (required by TimescaleDB hypertable).
 - Dependent writes (cve_details, attack_technique_tags) are skipped when the
 event row is a dedup conflict - they already exist from the original insert.
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
from app.ingest.normalise import _persist_event, update_source_health  # noqa: F401 - exposed for monkeypatching
from app.services.source_health import update_silent_failure_count, bump_last_event_at, record_ingest_stats
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
        text("SELECT id, credentials_enc, last_cursor, confidence FROM sources WHERE id = :id"),
        {"id": str(source_id)},
    ).one_or_none()
    if row is None:
        return None
    return {
        "id": row.id,
        "credentials_enc": row.credentials_enc,
        "last_cursor": row.last_cursor,
        "confidence": row.confidence,
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
    """Idempotent insert keyed on event_id - skip silently if already present."""
    stmt = pg_insert(CveDetails.__table__).values(event_id=event_id, **row)  # type: ignore[arg-type]
    stmt = stmt.on_conflict_do_nothing(index_elements=["event_id"])
    session.execute(stmt)


def _write_attack_tag(session: Session, event_id: uuid.UUID, technique_id: str,
                      url: str) -> None:
    session.execute(
        pg_insert(AttackTechniqueTag.__table__).values(  # type: ignore[arg-type]
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

 Backoff schedule: sleep 30s, 60s, 120s - one sleep per failed attempt
 (3 attempts total, 3 sleeps). 4xx non-429 fails fast without sleeping.
"""
    last_exc: BaseException | None = None
    for attempt_idx, sleep_s in enumerate(BACKOFF_SCHEDULE):
        try:
            return list(nvdlib.searchCVE_V2(**kwargs))
        except BaseException as e:  # noqa: BLE001
            code = _error_status_code(e)
            last_exc = e
            # 4xx non-429: fail fast - no sleep, propagate immediately
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

        parse_ok = 0
        parse_error = 0
        fetch_ok = 0
        fetch_error = 0

        try:
            cves = _fetch_with_backoff(**kwargs)
            fetch_ok = 1
        except BaseException as e:  # noqa: BLE001
            fetch_error = 1
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
            try:
                record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                session.commit()
            except Exception as stats_err:  # noqa: BLE001
                logger.warning("record_ingest_stats_failed source_id=%s err=%s", source_id, stats_err)
            return

        inserted = 0
        latest_mod: datetime | None = None
        attack_written = 0

        # Per-source project binding lookup - hoisted outside per-CVE loop.
        # Zero bindings → fall back to LEGACY (preserves prior behaviour for
        # unbound sources). One+ bindings → fan out one event per project.
        # Quick task 260429-tyq.
        from app.models.projects import LEGACY_PROJECT_ID  # noqa: PLC0415
        binding_rows = session.execute(
            text("SELECT project_id FROM project_sources WHERE source_id = :sid"),
            {"sid": str(source_id)},
        ).all()
        project_ids = [r[0] for r in binding_rows] or [LEGACY_PROJECT_ID]

        try:
            for cve in cves:
                try:
                    result = normalise_cve(cve, source_id)
                    if result is None:
                        logger.warning(
                            "feed_item_rejected reason=missing_dedup_key source_id=%s",
                            source_id,
                        )
                        parse_error += 1
                        continue
                    event_row, cve_details_row, attack_links = result

                    # SCR-01: inject score ONCE per CVE (pure function
                    # does not depend on project_id). Result is reused across
                    # per-project event rows in the inner fan-out loop.
                    if event_row.get("score") is None:
                        from app.services.scoring import score_event, ScoringWeights  # noqa: PLC0415
                        from app.services.scoring.defaults import DEFAULT_SOURCE_CONFIDENCE  # noqa: PLC0415
                        _nvd_src_conf = float(src.get("confidence") or DEFAULT_SOURCE_CONFIDENCE.get("nvd", 1.0))
                        _cvss = cve_details_row.get("cvss_v3_score")
                        _obs_at = event_row.get("observed_at")
                        if _obs_at is None:
                            from datetime import datetime, timezone  # noqa: PLC0415
                            _obs_at = datetime.now(timezone.utc)
                        _score_val, _scored_at_ts, _score_ver = score_event(
                            feed_type="nvd",
                            cvss_score=float(_cvss) if _cvss is not None else None,
                            brand_severity=None,
                            observed_at=_obs_at,
                            source_confidence=_nvd_src_conf,
                            tag_relevance=0.0,
                            weights=ScoringWeights(),
                        )
                        event_row["score"] = _score_val
                        event_row["scored_at"] = _scored_at_ts
                        event_row["score_version"] = _score_ver

                    # Fan-out: one event row per bound project. Each row gets its
                    # own cve_details + attack_tag children (cve_details has
                    # UNIQUE(event_id) so distinct event_id per project is correct).
                    # ON CONFLICT (project_id, source_id, content_hash, observed_at) DO NOTHING
                    # matches the 4-column unique index from migration 021.
                    for pid in project_ids:
                        per_event_row = {**event_row, "project_id": pid}
                        stmt = (
                            pg_insert(Event.__table__)  # type: ignore[arg-type]
                            .values(**per_event_row)
                            .on_conflict_do_nothing(
                                index_elements=["project_id", "source_id", "content_hash", "observed_at"]
                            )
                            .returning(Event.__table__.c.id)
                        )
                        result_row = session.execute(stmt).fetchone()
                        if result_row is None:
                            # Conflict - row already exists for this project; children too.
                            continue
                        event_id = result_row[0]
                        inserted += 1
                        # MON-01: bump last_event_at after successful insert
                        bump_last_event_at(session, source_id)

                        _write_cve_details(session, event_id, cve_details_row)
                        for technique_id, url in attack_links:
                            _write_attack_tag(session, event_id, technique_id, url)
                            attack_written += 1

                    last_mod_dt = cve_details_row.get("last_modified")
                    if last_mod_dt is not None and (latest_mod is None or last_mod_dt > latest_mod):
                        latest_mod = last_mod_dt

                    parse_ok += 1

                except Exception as cve_err:  # noqa: BLE001
                    parse_error += 1
                    logger.error(
                        "nvd_item_parse_failed source_id=%s cve_id=%s err=%s",
                        source_id,
                        getattr(cve, "id", "?"),
                        cve_err,
                    )

            if latest_mod is not None:
                cursor_iso = (latest_mod + timedelta(seconds=1)).isoformat()
                _advance_cursor(session, source_id, cursor_iso)

            update_source_health(session, source_id, status="ok", succeeded=True)
            update_silent_failure_count(session, source_id, inserted)

        finally:
            try:
                record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                session.commit()
            except Exception as stats_err:  # noqa: BLE001
                logger.warning("record_ingest_stats_failed source_id=%s err=%s", source_id, stats_err)

        logger.info(
            "nvd_poll_ok source_id=%s inserted=%d attack_tags=%d",
            source_id, inserted, attack_written,
        )


@dramatiq.actor(max_retries=0, queue_name="ingest")
def poll_nvd(source_id: str) -> None:
    poll_nvd_impl(source_id)
