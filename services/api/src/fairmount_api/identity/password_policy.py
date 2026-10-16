"""Approved V1 permanent-password validation; preserve the exact user's input."""

from __future__ import annotations

# A deliberately small local floor, not a substitute for rate limits or a future
# approved compromised-password screening process. Compare case-insensitively only
# for the denylist; never casefold/trim before hashing a valid password.
OBVIOUS_PASSWORDS = frozenset(
    {
        "password1234",
        "passwordpassword",
        "123456789012",
        "qwerty123456",
        "letmein123456",
        "admin12345678",
        "iloveyou1234",
    }
)


def validate_new_password(password: str) -> str:
    """Return the original passphrase or raise ValueError with no secret in the error."""
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise ValueError("Password must have 12 to 128 characters")
    if not password.isprintable() or not password.strip():
        raise ValueError("Password contains unsupported characters")
    # The 128-codepoint limit bounds UTF-8 data to <=512 bytes; this extra check
    # explicitly excludes invalid surrogate sequences in Python inputs.
    try:
        password.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Password contains unsupported characters") from exc
    if password.strip().casefold() in OBVIOUS_PASSWORDS or len(set(password.strip())) == 1:
        raise ValueError("Choose a less common password")
    return password
