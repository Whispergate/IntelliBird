"""Password hash + verify primitives - AUTH-01, AUTH-04.

pwdlib with Argon2id. Production params (OWASP 2024):
  time_cost=3, memory_cost=65536, parallelism=4 (~200ms/hash).

Test conftest swaps the singleton with faster params via the argon2_fast fixture.

verify_and_maybe_rehash follows pwdlib's verify_and_update contract so the caller
can persist a fresh hash when stored params drift from the current singleton config.

verify_dummy() exists specifically for the login-non-existent-user timing-safe path
(PITFALL 7 in 09-RESEARCH.md). Always-False; consumes ~Argon2-time to equalise the
response timing with a real hash verify.
"""
from __future__ import annotations

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

# Singleton - created once per process. conftest.argon2_fast fixture monkeypatches
# this with weaker params for unit tests.
password_hash: PasswordHash = PasswordHash((
    Argon2Hasher(time_cost=3, memory_cost=65536, parallelism=4),
))

# Pre-hashed dummy for timing-safe non-existent-user verify. Generated at import time.
_DUMMY_HASH: str = password_hash.hash("intellibird-dummy-password-xQ9k-not-a-real-account")


def hash_password(plaintext: str) -> str:
    """Hash a plaintext password with the current Argon2id params."""
    return password_hash.hash(plaintext)


def verify_and_maybe_rehash(plaintext: str, stored_hash: str) -> tuple[bool, str | None]:
    """Returns (is_valid, new_hash_or_None).

    Caller must persist new_hash_or_None when it is not None - this handles the
    rehash-on-login pattern when Argon2 params drift (e.g. operator raises memory_cost
    after production hardening).
    """
    valid, updated = password_hash.verify_and_update(plaintext, stored_hash)
    return bool(valid), (updated if updated is not None else None)


def verify_dummy() -> bool:
    """Timing-equaliser for non-existent-user login paths (PITFALL 7).

    Always returns False. The caller's /login handler MUST invoke this when the
    username lookup returns no row, so response time matches a real wrong-password
    verify and an attacker cannot enumerate usernames via timing.
    """
    password_hash.verify("wrong-guess-also-not-real", _DUMMY_HASH)
    return False
