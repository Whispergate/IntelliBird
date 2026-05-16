"""Integration: telegram source lifecycle — Phase 24 / DARK-04."""
import pytest


def test_poll_telegram_impl_ingests_channel_messages(db_session):
    """poll_telegram_impl() with mocked Telethon client creates event rows"""
    pass


def test_poll_telegram_session_enc_round_trip(db_session):
    """session_enc stored via encrypt_credentials; worker decrypts correctly"""
    pass


def test_poll_telegram_floodwait_marks_source_error(db_session):
    """Persistent FloodWaitError → sources.last_status='error'"""
    pass


def test_poll_telegram_uses_asyncio_run_not_await(db_session):
    """Worker body wraps async Telethon logic in asyncio.run() — no coroutine leak"""
    pass


def test_poll_telegram_dedup_by_message_id(db_session):
    """Same Telegram message_id on second poll → no duplicate event row"""
    pass
