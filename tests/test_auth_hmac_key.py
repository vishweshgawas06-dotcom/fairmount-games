"""Strict, separate deployment secret for authentication failure fingerprints."""

import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fairmount_api.identity.auth_hmac_key import load_auth_hmac_key

_TEST_BYTES = bytes(range(32))  # fixture only; never a deployment secret


class AuthHMACKeyTests(unittest.TestCase):
    def test_restricted_regular_file_and_env_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth.key"
            path.write_bytes(base64.b64encode(_TEST_BYTES) + b"\n")
            path.chmod(0o600)
            with patch.dict(os.environ, {"FAIRMOUNT_AUTH_HMAC_KEY_FILE": str(path)}):
                self.assertEqual(load_auth_hmac_key(), _TEST_BYTES)
            self.assertEqual(load_auth_hmac_key(path), _TEST_BYTES)
            path.write_bytes(base64.b64encode(_TEST_BYTES))
            self.assertEqual(load_auth_hmac_key(path), _TEST_BYTES)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                load_auth_hmac_key(path)

    def test_no_default_symlink_directory_short_or_noncanonical_key(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            load_auth_hmac_key()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth.key"
            path.write_bytes(base64.b64encode(_TEST_BYTES))
            path.chmod(0o600)
            link = Path(directory) / "link.key"
            link.symlink_to(path)
            for unsafe in (link, Path(directory), Path(directory) / "missing.key"):
                with self.subTest(path=unsafe), self.assertRaises(ValueError):
                    load_auth_hmac_key(unsafe)
            for raw in (b"short", b"a" * 44, b"A" * 42 + b"B=", b"a" * 100):
                path.write_bytes(raw)
                with self.subTest(raw=raw[:10]), self.assertRaises(ValueError):
                    load_auth_hmac_key(path)


if __name__ == "__main__":
    unittest.main()
