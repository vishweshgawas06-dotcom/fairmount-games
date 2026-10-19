"""Load versioned MFA keys from an owner-controlled secret file outside Git/DB.

No default or generated key is available at runtime. The file path may be supplied
through FAIRMOUNT_MFA_KEY_FILE; the file contents must never enter logs or errors.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

MAX_KEYRING_BYTES = 4096


@dataclass(frozen=True)
class MFAKeyring:
    active_version: int
    keys: Mapping[int, bytes]

    def key_for(self, version: int) -> bytes:
        """Return a configured historical or active key, never a fallback key."""
        if not isinstance(version, int) or isinstance(version, bool) or version not in self.keys:
            raise ValueError("MFA key version unavailable")
        return self.keys[version]

    def active_key(self) -> tuple[int, bytes]:
        return self.active_version, self.key_for(self.active_version)


def load_mfa_keyring(path: str | Path | None = None) -> MFAKeyring:
    """Require a regular, owner-owned, non-symlink file with mode 0600 or stricter.

    Format: {"active_version": 1, "keys": {"1": "base64-of-32-random-bytes"}}.
    Older versions may remain in the file during a separately reviewed rotation.
    """
    selected = path if path is not None else os.environ.get("FAIRMOUNT_MFA_KEY_FILE")
    if not selected:
        raise ValueError("MFA key file is not configured")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW
    try:
        fd = os.open(selected, flags)
    except OSError as exc:
        raise ValueError("MFA key file cannot be opened safely") from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o177
            or info.st_size > MAX_KEYRING_BYTES
        ):
            raise ValueError("MFA key file has unsafe ownership, permissions or size")
        raw = os.read(fd, MAX_KEYRING_BYTES + 1)
        if len(raw) > MAX_KEYRING_BYTES:
            raise ValueError("MFA key file is too large")
    finally:
        os.close(fd)

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        obj: dict[str, object] = {}
        for name, value in pairs:
            if name in obj:
                raise ValueError("Invalid MFA key file")
            obj[name] = value
        return obj

    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
        if not isinstance(document, dict) or set(document) != {"active_version", "keys"}:
            raise ValueError("Invalid MFA key file")
        version = document["active_version"]
        encoded_keys = document["keys"]
        if (
            not isinstance(version, int)
            or isinstance(version, bool)
            or not 1 <= version <= 2**31
            or not isinstance(encoded_keys, dict)
            or not 1 <= len(encoded_keys) <= 8
        ):
            raise ValueError("Invalid MFA key file")
        keys: dict[int, bytes] = {}
        for label, encoded in encoded_keys.items():
            if (
                not isinstance(label, str)
                or not label.isascii()
                or not label.isdecimal()
                or len(label) > 10
                or str(int(label)) != label
            ):
                raise ValueError("Invalid MFA key file")
            number = int(label)
            if not 1 <= number <= 2**31 or not isinstance(encoded, str) or len(encoded) != 44:
                raise ValueError("Invalid MFA key file")
            key = base64.b64decode(encoded, validate=True)
            if len(key) != 32:
                raise ValueError("Invalid MFA key file")
            keys[number] = key
        if version not in keys or len(set(keys.values())) != len(keys):
            raise ValueError("Invalid MFA key file")
        return MFAKeyring(active_version=version, keys=MappingProxyType(keys))
    except (UnicodeError, json.JSONDecodeError, binascii.Error, OverflowError) as exc:
        raise ValueError("Invalid MFA key file") from exc
