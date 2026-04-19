"""Password hash/verify/timing-safe-dummy unit tests — AUTH-01/04."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _fast_argon2(argon2_fast):
    """Activate the argon2_fast fixture from conftest — keeps each Argon2 op under ~5ms."""
    yield


def test_hash_returns_argon2id_string():
    from app.security.passwords import hash_password
    stored = hash_password("correct-horse-battery-staple")
    assert stored.startswith("$argon2id$"), stored[:30]


def test_verify_correct_password():
    from app.security.passwords import hash_password, verify_and_maybe_rehash
    stored = hash_password("correct-horse-battery-staple")
    valid, new_hash = verify_and_maybe_rehash("correct-horse-battery-staple", stored)
    assert valid is True
    assert new_hash is None  # same params, no rehash needed


def test_verify_wrong_password():
    from app.security.passwords import hash_password, verify_and_maybe_rehash
    stored = hash_password("correct-horse-battery-staple")
    valid, new_hash = verify_and_maybe_rehash("incorrect-horse", stored)
    assert valid is False
    assert new_hash is None


def test_verify_and_update_rehashes_on_param_drift():
    """If the stored hash was made with weaker params, a successful verify returns a new hash."""
    from pwdlib import PasswordHash
    from pwdlib.hashers.argon2 import Argon2Hasher
    weak = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1),))
    old_stored = weak.hash("correct-horse-battery-staple")

    # Now bump the process-wide singleton to slightly stronger params and verify through it.
    # The argon2_fast fixture already patched the singleton to time_cost=1 — re-patch to
    # time_cost=2 so verify_and_update sees a drift.
    from app.security import passwords as pw_module
    stronger = PasswordHash((Argon2Hasher(time_cost=2, memory_cost=8, parallelism=1),))
    pw_module.password_hash = stronger

    valid, new_hash = pw_module.verify_and_maybe_rehash("correct-horse-battery-staple", old_stored)
    assert valid is True
    assert new_hash is not None  # rehash fired
    assert new_hash != old_stored


def test_verify_dummy_returns_false():
    """verify_dummy() is used for timing-safe non-existent-user login."""
    from app.security.passwords import verify_dummy
    assert verify_dummy() is False
