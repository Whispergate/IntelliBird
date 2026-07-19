"""AES-256-GCM credentials encrypt/decrypt - / SRC-04.

The sources.credentials_enc column stores the base64url-encoded
(nonce || ciphertext || tag) output of AESGCM. Key is derived from
Settings.SECRET_KEY via HKDF-SHA256 with a fixed info string so the
key is deterministic per deployment.
"""
from __future__ import annotations

import base64
import re

import pytest
from cryptography.exceptions import InvalidTag

from app.crypto import _derive_key, decrypt_credentials, encrypt_credentials

SECRET = "a" * 32 + "deadbeef"  # ≥ 32 chars, passes Settings validator
OTHER = "b" * 32 + "feedface"
URLSAFE_B64 = re.compile(r"^[A-Za-z0-9_\-]+=*$")


@pytest.mark.parametrize("creds", [
    {"type": "basic", "username": "alice", "password": "s3cret"},
    {"type": "bearer", "token": "abcdef.ghijkl.mnopqr"},
    {"type": "apiKey", "key": "NVD_TEST_KEY_xxxxxxxxxxxxxxxxxxx"},
    {"type": "basic", "username": "u", "password": "p", "extra": ["a", "b"]},
])
def test_round_trip(creds: dict) -> None:
    blob = encrypt_credentials(SECRET, creds)
    assert decrypt_credentials(SECRET, blob) == creds


def test_nonce_randomness() -> None:
    creds = {"type": "bearer", "token": "x"}
    a = encrypt_credentials(SECRET, creds)
    b = encrypt_credentials(SECRET, creds)
    assert a != b, "nonce must be random per-encrypt call"


def test_wrong_key_fails() -> None:
    blob = encrypt_credentials(SECRET, {"type": "bearer", "token": "x"})
    with pytest.raises(InvalidTag):
        decrypt_credentials(OTHER, blob)


def test_tamper_detection() -> None:
    blob = encrypt_credentials(SECRET, {"type": "bearer", "token": "x"})
    raw = bytearray(base64.urlsafe_b64decode(blob))
    # Flip a byte after the 12-byte nonce (in the ciphertext+tag region)
    raw[15] ^= 0x01
    tampered = base64.urlsafe_b64encode(bytes(raw)).decode()
    with pytest.raises(InvalidTag):
        decrypt_credentials(SECRET, tampered)


def test_blob_is_urlsafe_base64() -> None:
    blob = encrypt_credentials(SECRET, {"type": "bearer", "token": "x"})
    assert URLSAFE_B64.match(blob)


def test_key_derivation_stable() -> None:
    k1 = _derive_key(SECRET)
    k2 = _derive_key(SECRET)
    assert k1 == k2
    assert len(k1) == 32
    assert _derive_key(OTHER) != k1
