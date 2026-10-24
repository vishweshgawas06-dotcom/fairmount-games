"""Restricted deployment-owned key loader for pseudonymous auth-attempt HMACs.

Separate from owner TOTP encryption keys. Never auto-generate, default to a dev
secret, read from an unchecked symlink, or print the key/path in an error.
"""

from __future__ import annotations

import base64
import binascii
import os
import stat
from pathlib import Path

_MAX_BYTES = 64


def load_auth_hmac_key(path: str | Path | None = None) -> bytes:
    """Read exactly 32 random bytes encoded as strict base64 from mode 0600 file.

    File must be owned by the effective process user, be regular and not a
    symlink. A single trailing newline is allowed for offline key-file tools.
    Changing this key changes lookup digests and resets active rate windows;
    that rotation requires an operations review before production use.
    """
    selected = path if path is not None else os.environ.get("FAIRMOUNT_AUTH_HMAC_KEY_FILE")
    if not selected:
        raise ValueError("Authentication HMAC key file is not configured")
    try:
        fd = os.open(selected, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        raise ValueError("Authentication HMAC key file cannot be opened safely") from None
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o177
            or not 44 <= info.st_size <= 45
        ):
            raise ValueError("Authentication HMAC key file is unsafe")
        raw = os.read(fd, _MAX_BYTES + 1)
    finally:
        os.close(fd)
    encoded = raw[:-1] if raw.endswith(b"\n") else raw
    if len(encoded) != 44 or len(raw) not in (44, 45):
        raise ValueError("Invalid authentication HMAC key file")
    try:
        key = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid authentication HMAC key file") from exc
    if len(key) != 32 or base64.b64encode(key) != encoded:
        raise ValueError("Invalid authentication HMAC key file")
    return key
