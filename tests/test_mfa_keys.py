"""Restricted versioned MFA key loading; tests never use deployment secrets."""

import base64
import json
import os
import secrets
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fairmount_api.identity.mfa_keys import load_mfa_keyring


class MFAKeyFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "keys.json"
        self.first = secrets.token_bytes(32)
        self.second = secrets.token_bytes(32)

    def write_keys(self, document: dict, mode: int = 0o600) -> None:
        self.path.write_text(json.dumps(document), encoding="utf-8")
        self.path.chmod(mode)

    def document(self) -> dict:
        return {
            "active_version": 2,
            "keys": {
                "1": base64.b64encode(self.first).decode("ascii"),
                "2": base64.b64encode(self.second).decode("ascii"),
            },
        }

    def test_loads_current_and_old_key_without_default(self) -> None:
        self.write_keys(self.document())
        ring = load_mfa_keyring(self.path)
        self.assertEqual(ring.active_key(), (2, self.second))
        self.assertEqual(ring.key_for(1), self.first)
        with self.assertRaises(ValueError):
            ring.key_for(3)
        with self.assertRaises(TypeError):
            ring.keys[3] = secrets.token_bytes(32)
        with patch.dict(os.environ, {"FAIRMOUNT_MFA_KEY_FILE": str(self.path)}):
            self.assertEqual(load_mfa_keyring().active_version, 2)
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            load_mfa_keyring()

    def test_rejects_unsafe_files_and_symlinks(self) -> None:
        self.write_keys(self.document(), mode=0o644)
        with self.assertRaises(ValueError):
            load_mfa_keyring(self.path)
        self.path.chmod(0o700)
        with self.assertRaises(ValueError):
            load_mfa_keyring(self.path)
        self.path.chmod(0o600)
        link = self.path.parent / "link.json"
        link.symlink_to(self.path)
        with self.assertRaises(ValueError):
            load_mfa_keyring(link)
        with self.assertRaises(ValueError):
            load_mfa_keyring(self.path.parent)
        with self.assertRaises(ValueError):
            load_mfa_keyring(self.path.parent / "missing.json")
        self.path.write_bytes(b"x" * 4097)
        with self.assertRaises(ValueError):
            load_mfa_keyring(self.path)

    def test_rejects_invalid_format_version_keys_and_duplicates(self) -> None:
        bad = (
            {"active_version": 3, "keys": self.document()["keys"]},
            {"active_version": True, "keys": self.document()["keys"]},
            {"active_version": 1, "keys": {"01": base64.b64encode(self.first).decode()}},
            {"active_version": 1, "keys": {"1": "A" * 44}},
            {"active_version": 1, "keys": {"1": "!" * 44}},
            {"active_version": 1, "keys": {"1": base64.b64encode(b"short").decode()}},
            {"active_version": 2, "keys": {"1": base64.b64encode(self.first).decode()}},
            {"active_version": 1, "keys": {"1": base64.b64encode(self.first).decode()},
             "unexpected": "extra"},
        )
        for index, document in enumerate(bad):
            with self.subTest(index=index):
                self.write_keys(document)
                with self.assertRaises(ValueError):
                    load_mfa_keyring(self.path)
        self.path.write_text('{"active_version":1,"active_version":2,"keys":{}}')
        with self.assertRaises(ValueError):
            load_mfa_keyring(self.path)


if __name__ == "__main__":
    unittest.main()
