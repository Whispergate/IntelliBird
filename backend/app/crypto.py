"""AES-256-GCM encryption for sources.credentials_enc.

Key is derived from Settings.SECRET_KEY via HKDF-SHA256 with a fixed
info string. Output blob = base64url(nonce(12) || ciphertext || tag(16)).

Public API:
 encrypt_credentials(secret, creds_dict) -> base64url-str
 decrypt_credentials(secret, blob_str) -> creds_dict

 source CRUD reads `Settings.SECRET_KEY` and passes to these
functions at each write/read. worker plans call decrypt only.
"""
from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_HKDF_INFO: bytes = b"intellibird-credentials"
_NONCE_LEN: int = 12  # NIST-recommended 96-bit nonce for AES-GCM
_KEY_LEN: int = 32    # AES-256


def _derive_key(secret: str) -> bytes:
    """HKDF-SHA256(secret → 32-byte AES key)."""
    return HKDF(
        algorithm=SHA256(),
        length=_KEY_LEN,
        salt=None,
        info=_HKDF_INFO,
    ).derive(secret.encode("utf-8"))


def encrypt_credentials(secret: str, creds: dict) -> str:
    """Encrypt a JSON-serialisable dict → base64url str.

 Output layout: base64url(nonce || AESGCM.encrypt(plaintext) + tag)
"""
    key = _derive_key(secret)
    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_LEN)
    plaintext = json.dumps(creds, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ct_and_tag = aesgcm.encrypt(nonce, plaintext, associated_data=None)
    return base64.urlsafe_b64encode(nonce + ct_and_tag).decode("ascii")


def decrypt_credentials(secret: str, blob: str) -> dict:
    """Reverse of encrypt_credentials. Raises InvalidTag on wrong key or tamper."""
    key = _derive_key(secret)
    aesgcm = AESGCM(key)
    raw = base64.urlsafe_b64decode(blob.encode("ascii"))
    nonce, ct_and_tag = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
    plaintext = aesgcm.decrypt(nonce, ct_and_tag, associated_data=None)
    return json.loads(plaintext.decode("utf-8"))
