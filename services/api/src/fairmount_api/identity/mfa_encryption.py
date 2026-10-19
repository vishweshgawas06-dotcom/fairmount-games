"""Owner TOTP encryption primitive; key custody and database storage are elsewhere.

The caller supplies a 256-bit deployment key from outside source and PostgreSQL.
No default key, environment loader or enrollment route exists here.
"""

from __future__ import annotations

import base64
import binascii
import re
import secrets
import uuid
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass(frozen=True)
class EncryptedTOTPSecret:
    key_version: int
    nonce: str
    ciphertext: str


def _associated_data(account_id: uuid.UUID, key_version: int) -> bytes:
    if not isinstance(account_id, uuid.UUID):
        raise ValueError("Invalid owner account reference")
    if (
        not isinstance(key_version, int)
        or isinstance(key_version, bool)
        or not 1 <= key_version <= 2**31
    ):
        raise ValueError("Invalid MFA key version")
    return b"fairmount:owner-totp:v1:" + account_id.bytes + key_version.to_bytes(4, "big")


def _validate_key(key: bytes) -> None:
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError("MFA encryption key must be 32 bytes")


def encrypt_totp_secret(
    secret: str, *, account_id: uuid.UUID, key: bytes, key_version: int
) -> EncryptedTOTPSecret:
    """Encrypt a 160-bit Base32 TOTP seed with owner-bound authenticated data."""
    _validate_key(key)
    associated_data = _associated_data(account_id, key_version)
    if not isinstance(secret, str) or not re.fullmatch(r"[A-Z2-7]{32}", secret):
        raise ValueError("Invalid TOTP seed")
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(nonce, secret.encode("ascii"), associated_data)
    return EncryptedTOTPSecret(
        key_version=key_version,
        nonce=base64.urlsafe_b64encode(nonce).decode("ascii"),
        ciphertext=base64.urlsafe_b64encode(ciphertext).decode("ascii"),
    )


def decrypt_totp_secret(
    encrypted: EncryptedTOTPSecret, *, account_id: uuid.UUID, key: bytes
) -> str:
    """Fail closed on wrong account/key/version, tampering or malformed ciphertext."""
    _validate_key(key)
    if not isinstance(encrypted, EncryptedTOTPSecret):
        raise ValueError("Invalid encrypted MFA seed")
    associated_data = _associated_data(account_id, encrypted.key_version)
    if (
        not isinstance(encrypted.nonce, str)
        or len(encrypted.nonce) != 16
        or not isinstance(encrypted.ciphertext, str)
        or len(encrypted.ciphertext) != 64
    ):
        raise ValueError("Invalid encrypted MFA seed")
    try:
        nonce = base64.b64decode(encrypted.nonce, altchars=b"-_", validate=True)
        ciphertext = base64.b64decode(encrypted.ciphertext, altchars=b"-_", validate=True)
        if len(nonce) != 12 or len(ciphertext) != 48:
            raise ValueError("Invalid encrypted MFA seed")
        secret = AESGCM(key).decrypt(nonce, ciphertext, associated_data).decode("ascii")
    except (InvalidTag, ValueError, UnicodeError, binascii.Error) as exc:
        raise ValueError("Invalid encrypted MFA seed") from exc
    if not re.fullmatch(r"[A-Z2-7]{32}", secret):
        raise ValueError("Invalid encrypted MFA seed")
    return secret
