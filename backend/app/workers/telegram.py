"""Telegram public-channel ingestion actor — DARK-04.

Uses Telethon StringSession stored encrypted in sources.session_enc.
api_id and api_hash are stored encrypted in sources.scrape_config as
{"api_id_enc": ..., "api_hash_enc": ..., "channel": "@handle"}.

PUBLIC CHANNELS ONLY. join_channel() is never called.
FloodWaitError: sleep min(seconds, 60); persistent flood → status='error'.

asyncio.run() wraps all Telethon async calls — Dramatiq actors are sync.

SESSION PERSISTENCE: _poll_telegram_async returns (messages, new_session_str)
where new_session_str = client.session.save(). poll_telegram_impl re-encrypts
and writes this back to sources.session_enc so every poll is authenticated
without needing to bootstrap a new session.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from contextlib import contextmanager
from datetime import timezone
from typing import Iterator

import dramatiq
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.ingest.normalise import _persist_event_for_bindings, update_source_health
from app.services.source_health import record_ingest_stats, update_silent_failure_count

logger = logging.getLogger(__name__)


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
        text(
            "SELECT id, url, scrape_config, session_enc, opsec_authorised "
            "FROM sources WHERE id = :id"
        ),
        {"id": str(source_id)},
    ).one_or_none()
    if row is None:
        return None
    return {
        "id": row.id,
        "url": row.url,
        "scrape_config": row.scrape_config,
        "session_enc": row.session_enc,
        "opsec_authorised": row.opsec_authorised,
    }


async def _poll_telegram_async(
    api_id: int,
    api_hash: str,
    session_str: str,
    channel: str,
    *,
    min_id: int = 0,
) -> tuple[list[dict], str]:
    """Fetch recent messages from a public Telegram channel.

    Returns a tuple of (messages, new_session_str) where new_session_str is
    the result of client.session.save() — caller must re-encrypt and persist
    this to sources.session_enc so the next poll reconnects authenticated.
    """
    from telethon import TelegramClient  # noqa: PLC0415 — lazy: only installed with darkweb profile
    from telethon.errors import FloodWaitError  # noqa: PLC0415
    from telethon.sessions import StringSession  # noqa: PLC0415

    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    messages: list[dict] = []
    flood_count = 0
    try:
        await client.connect()
        try:
            async for msg in client.iter_messages(channel, min_id=min_id, limit=100):
                if msg.text:
                    messages.append(
                        {
                            "id": msg.id,
                            "date": msg.date,
                            "text": msg.text,
                            "channel": channel,
                        }
                    )
        except FloodWaitError as e:
            flood_count += 1
            wait = min(e.seconds, 60)
            logger.warning(
                "telegram_flood_wait channel=%s wait=%ds flood_count=%d",
                channel,
                wait,
                flood_count,
            )
            await asyncio.sleep(wait)
            if flood_count >= 2:
                raise  # persistent flood — caller marks status='error'
    finally:
        # Save session state before disconnecting so next poll reconnects authenticated.
        new_session_str = client.session.save()
        await client.disconnect()
    return messages, new_session_str


def _build_event_row(msg: dict, source_id: uuid.UUID) -> dict | None:
    """Convert a Telegram message dict to the event row shape expected by _persist_event_for_bindings."""
    text_body = msg.get("text", "")
    if not text_body:
        return None
    channel = msg.get("channel", "unknown")
    observed_at = msg.get("date")
    if observed_at and observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    content_hash = hashlib.sha256(
        f"{channel}:{msg['id']}:{text_body}".encode()
    ).hexdigest()
    return {
        "source_id": str(source_id),
        "title": f"[Telegram:{channel}] {text_body[:120]}",
        "description": text_body,
        "url": f"https://t.me/{channel.lstrip('@')}/{msg['id']}",
        "observed_at": observed_at,
        "content_hash": content_hash,
        "raw_stix": None,
    }


def poll_telegram_impl(source_id_str: str) -> None:
    """Sync actor body — invoked directly by integration tests."""
    source_id = uuid.UUID(source_id_str)
    inserted = 0
    deduped = 0
    parse_ok = 0
    parse_error = 0
    fetch_ok = 0
    fetch_error = 0

    with _open_session() as session:
        src = _fetch_source_row(session, source_id)
        if src is None:
            logger.error("telegram_poll_source_missing source_id=%s", source_id)
            return

        if not src.get("opsec_authorised"):
            logger.error(
                "telegram_poll_opsec_not_authorised source_id=%s", source_id
            )
            update_source_health(session, source_id, status="config_error", succeeded=False)
            try:
                record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                session.commit()
            except Exception:  # noqa: BLE001
                pass
            return

        cfg = src.get("scrape_config") or {}
        session_enc = src.get("session_enc")
        if not session_enc:
            logger.error(
                "telegram_poll_no_session_enc source_id=%s", source_id
            )
            update_source_health(session, source_id, status="config_error", succeeded=False)
            try:
                record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                session.commit()
            except Exception:  # noqa: BLE001
                pass
            return

        try:
            from app.config import settings  # noqa: PLC0415
            from app.crypto import decrypt_credentials  # noqa: PLC0415

            creds = decrypt_credentials(settings.SECRET_KEY, session_enc)
            session_str = creds.get("session", "")
            api_id = int(decrypt_credentials(settings.SECRET_KEY, cfg["api_id_enc"])["v"])
            api_hash = decrypt_credentials(settings.SECRET_KEY, cfg["api_hash_enc"])["v"]
            channel = cfg.get("channel", "")
        except Exception as e:  # noqa: BLE001
            logger.error(
                "telegram_poll_credential_decrypt_failed source_id=%s err=%s", source_id, e
            )
            update_source_health(session, source_id, status="config_error", succeeded=False)
            try:
                record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                session.commit()
            except Exception:  # noqa: BLE001
                pass
            return

        if not channel:
            logger.error("telegram_poll_no_channel source_id=%s", source_id)
            update_source_health(session, source_id, status="config_error", succeeded=False)
            try:
                record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                session.commit()
            except Exception:  # noqa: BLE001
                pass
            return

        try:
            messages, new_session_str = asyncio.run(
                _poll_telegram_async(api_id, api_hash, session_str, channel)
            )
            fetch_ok = 1
        except Exception as e:  # noqa: BLE001
            fetch_error = 1
            logger.warning(
                "telegram_poll_fetch_failed source_id=%s channel=%s err=%s",
                source_id,
                channel,
                e,
            )
            update_source_health(session, source_id, status="error", succeeded=False)
            try:
                record_ingest_stats(session, source_id, parse_ok, parse_error, fetch_ok, fetch_error)
                session.commit()
            except Exception:  # noqa: BLE001
                pass
            return

        # Persist the updated session string so the next poll reconnects authenticated.
        # Do this BEFORE processing messages — if message processing fails we still
        # want the session saved.
        try:
            from app.config import settings  # noqa: PLC0415
            from app.crypto import encrypt_credentials  # noqa: PLC0415

            new_enc = encrypt_credentials(settings.SECRET_KEY, {"session": new_session_str})
            session.execute(
                text("UPDATE sources SET session_enc = :new_enc WHERE id = :source_id"),
                {"new_enc": new_enc, "source_id": str(source_id)},
            )
            session.commit()
        except Exception as enc_err:  # noqa: BLE001
            # Non-fatal: log and continue processing messages.
            logger.warning(
                "telegram_session_enc_update_failed source_id=%s err=%s", source_id, enc_err
            )

        try:
            for msg in messages:
                try:
                    row = _build_event_row(msg, source_id)
                    if row is None:
                        continue
                    rc, _ = _persist_event_for_bindings(session, row, source_id)
                    if rc >= 1:
                        inserted += rc
                        parse_ok += 1
                    else:
                        deduped += 1
                        parse_ok += 1
                except Exception as entry_err:  # noqa: BLE001
                    parse_error += 1
                    logger.error(
                        "telegram_item_persist_failed source_id=%s err=%s",
                        source_id,
                        entry_err,
                    )
            update_source_health(session, source_id, status="ok", succeeded=True)
            update_silent_failure_count(session, source_id, inserted)
        finally:
            try:
                record_ingest_stats(
                    session, source_id, parse_ok, parse_error, fetch_ok, fetch_error
                )
                session.commit()
            except Exception:  # noqa: BLE001
                pass

        logger.info(
            "telegram_poll_ok source_id=%s channel=%s inserted=%d deduped=%d",
            source_id,
            channel,
            inserted,
            deduped,
        )


@dramatiq.actor(max_retries=0, queue_name="darkweb")
def poll_telegram(source_id: str) -> None:
    poll_telegram_impl(source_id)
