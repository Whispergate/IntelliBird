"""Integration: migration 025_darkweb_sources round-trip - DARK-01..07.

Verifies:
  - feed_type_enum gains 'tor_html', 'paste', 'telegram' values
  - sources.opsec_authorised column exists with DEFAULT false
  - sources.session_enc column exists as nullable TEXT
  - Confidence backfill UPDATE is idempotent (no-op on empty table)
  - down() cleanly removes columns and enum values (or documents skip if PG limitation)
"""


def test_migration_025_adds_feed_type_enum_values():
    """After upgrade, INSERT INTO sources (feed_type) VALUES ('tor_html') succeeds"""
    pass


def test_migration_025_adds_opsec_authorised_column():
    """sources.opsec_authorised column exists; DEFAULT false; NOT NULL"""
    pass


def test_migration_025_adds_session_enc_column():
    """sources.session_enc column exists; nullable TEXT"""
    pass


def test_migration_025_upgrade_is_idempotent():
    """Running upgrade twice does not raise (IF NOT EXISTS guards)"""
    pass
