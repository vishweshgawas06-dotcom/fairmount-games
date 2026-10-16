"""Cryptographic primitives for later, separately reviewed credential workflows.

This module neither issues credentials to accounts nor authenticates sessions. Callers
must supply expiry, single-use consumption, rate limits and audit in a DB transaction.
Never log or persist readable passwords or activation secrets.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

# Explicit resource parameters avoid accidental changes across library releases.
# Benchmark these against deployment hardware before production authentication.
PASSWORD_HASHER = PasswordHasher(
    time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16, type=Type.ID
)


def hash_password(password: str) -> str:
    """Hash a nonempty password using a fresh Argon2id salt each call."""
    if not isinstance(password, str) or not password:
        raise ValueError("Password must be a nonempty string")
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Reject invalid or mismatched Argon2 hashes without disclosing secrets."""
    if not isinstance(password, str) or not isinstance(stored_hash, str):
        return False
    if not stored_hash.startswith("$argon2id$"):
        return False
    try:
        return PASSWORD_HASHER.verify(stored_hash, password)
    except (InvalidHashError, VerificationError):
        return False


def generate_initial_secret() -> str:
    """Create a 256-bit, URL-safe one-time credential for protected handoff."""
    return secrets.token_urlsafe(32)


def initial_secret_digest(secret: str) -> str:
    """Store only the SHA-256 digest of a high-entropy generated secret."""
    if not isinstance(secret, str) or not secret:
        raise ValueError("Initial secret must be a nonempty string")
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def verify_initial_secret(secret: str, stored_digest: str) -> bool:
    """Constant-time compare of a supplied secret against its stored digest."""
    if not isinstance(secret, str) or not isinstance(stored_digest, str):
        return False
    if len(secret) > 256 or len(stored_digest) != 64:
        return False
    candidate = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    return hmac.compare_digest(candidate, stored_digest)
