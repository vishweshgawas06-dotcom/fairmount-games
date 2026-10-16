"""Pure owner-MFA primitives; not enrollment, secret storage or session authorization.

A future PostgreSQL service must encrypt the TOTP seed, rate-limit attempts, enforce
monotonic matched steps, atomically consume recovery codes and audit every change.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import struct

TOTP_PERIOD_SECONDS = 30
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
RECOVERY_CODE_COUNT = 10


def generate_totp_secret() -> str:
    """Create a 160-bit Base32 authenticator seed (never persist it in plaintext)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def totp_code(secret: str, timestamp: int) -> str:
    """RFC 6238 SHA-1 TOTP, 6 digits, 30-second period."""
    if not isinstance(secret, str) or not re.fullmatch(r"[A-Z2-7]{32}", secret):
        raise ValueError("Invalid TOTP seed")
    if not isinstance(timestamp, int) or isinstance(timestamp, bool) or timestamp < 0:
        raise ValueError("Invalid TOTP timestamp")
    key = base64.b32decode(secret, casefold=False)
    counter = timestamp // TOTP_PERIOD_SECONDS
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def matched_totp_step(secret: str, code: str, timestamp: int) -> int | None:
    """Return matching step within ±30s; caller must reject steps already used."""
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        return None
    if not isinstance(timestamp, int) or isinstance(timestamp, bool) or timestamp < 0:
        raise ValueError("Invalid TOTP timestamp")
    current_step = timestamp // TOTP_PERIOD_SECONDS
    matched = None
    for step in range(max(0, current_step - 1), current_step + 2):
        if hmac.compare_digest(totp_code(secret, step * TOTP_PERIOD_SECONDS), code):
            matched = step
    return matched


def generate_recovery_codes() -> tuple[str, ...]:
    """Generate ten distinct 80-bit, human-readable one-time code candidates."""
    codes: set[str] = set()
    while len(codes) < RECOVERY_CODE_COUNT:
        codes.add("".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(16)))
    return tuple(sorted(codes))


def recovery_code_digest(code: str) -> str:
    """Hash a generated recovery code; caller stores only this digest."""
    if not isinstance(code, str) or not re.fullmatch(rf"[{RECOVERY_ALPHABET}]{{16}}", code):
        raise ValueError("Invalid recovery code format")
    return hashlib.sha256(code.encode("ascii")).hexdigest()


def verify_recovery_code(code: str, digest: str) -> bool:
    """Compare a supplied code and digest; one-time consumption belongs in the DB."""
    if (
        not isinstance(code, str)
        or not code.isascii()
        or len(code) > 19
        or not isinstance(digest, str)
        or len(digest) != 64
    ):
        return False
    canonical = code.upper().replace("-", "")
    if not re.fullmatch(rf"[{RECOVERY_ALPHABET}]{{16}}", canonical):
        return False
    return hmac.compare_digest(recovery_code_digest(canonical), digest)
