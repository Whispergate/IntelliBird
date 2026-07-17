"""MISP push actor — MISP-03.

Dramatiq fire-and-forget actor on 'ingest' queue.
Triggered after ai_suggestion status transitions to 'confirmed'
AND the suggestion_type is in misp_configs.push_types.

Never auto-pushes pending or discarded suggestions.
Push failure is logged but does NOT roll back the confirmation.
"""
from __future__ import annotations

import logging

import dramatiq

log = logging.getLogger(__name__)


def _should_push(*, status: str, suggestion_type: str, push_types: list[str]) -> bool:
    """True only when status is 'confirmed' AND suggestion_type is in push_types."""
    return status == "confirmed" and suggestion_type in push_types


@dramatiq.actor(queue_name="ingest", max_retries=1, min_backoff=5_000)
def misp_push_suggestion(suggestion_id: str, project_id: str) -> None:
    """Fire-and-forget push to MISP. Failure logged but never surfaces to analyst."""
    import psycopg2  # noqa: PLC0415
    from pymisp import PyMISP, MISPEvent  # noqa: PLC0415
    from app.config import settings  # noqa: PLC0415
    from app.crypto import decrypt_credentials  # noqa: PLC0415

    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://").replace("+asyncpg", "")
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            # Load misp_config for this project
            cur.execute(
                "SELECT url, api_key_enc, enabled, ssl_verify "
                "FROM misp_configs WHERE project_id = %s AND enabled = TRUE",
                (project_id,),
            )
            row = cur.fetchone()
            if row is None:
                log.debug("misp_push_skipped suggestion_id=%s reason=no_enabled_config", suggestion_id)
                return

            url, api_key_enc, _, ssl_verify = row

            # Load suggestion content
            cur.execute(
                "SELECT suggestion_type, content FROM ai_suggestions WHERE id = %s",
                (suggestion_id,),
            )
            sug = cur.fetchone()
            if sug is None:
                log.warning("misp_push_suggestion_not_found suggestion_id=%s", suggestion_id)
                return
            suggestion_type, content = sug
    finally:
        conn.close()

    try:
        creds = decrypt_credentials(settings.SECRET_KEY, api_key_enc)
        misp = PyMISP(url=url, key=creds["api_key"], ssl=ssl_verify)
        event = MISPEvent()
        event.info = f"IntelliBird: Confirmed {suggestion_type} suggestion"
        event.distribution = 0  # org-only
        # Add content as a comment attribute (generic — analyst reviews in MISP)
        event.add_attribute("comment", str(content))
        misp.add_event(event)
        log.info(
            "misp_push_success suggestion_id=%s project_id=%s type=%s",
            suggestion_id, project_id, suggestion_type,
        )
    except Exception as exc:  # noqa: BLE001
        log.error(
            "misp_push_failed suggestion_id=%s error=%s",
            suggestion_id, exc,
        )
        # Do NOT re-raise — fire-and-forget; confirmation already committed


def _maybe_push_to_misp(
    suggestion_id: str,
    project_id: str,
    suggestion_type: str,
    status: str,
    push_types: list[str],
) -> None:
    """Called post-commit from confirm_suggestion. Enqueues push actor if opt-in."""
    if _should_push(status=status, suggestion_type=suggestion_type, push_types=push_types):
        misp_push_suggestion.send_with_options(
            args=(suggestion_id, project_id), delay=0
        )
        log.debug(
            "misp_push_enqueued suggestion_id=%s type=%s project=%s",
            suggestion_id, suggestion_type, project_id,
        )


__all__ = ["misp_push_suggestion", "_should_push", "_maybe_push_to_misp"]
