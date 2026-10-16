"""Authenticated owner-bound TOTP encryption, with no deployment key in source."""

import secrets
import unittest
import uuid
from dataclasses import replace

from fairmount_api.identity.mfa import generate_totp_secret
from fairmount_api.identity.mfa_encryption import (
    decrypt_totp_secret,
    encrypt_totp_secret,
)


class MFAEncryptionTests(unittest.TestCase):
    def test_roundtrip_random_nonce_and_owner_binding(self) -> None:
        key = secrets.token_bytes(32)
        owner = uuid.uuid4()
        secret = generate_totp_secret()
        first = encrypt_totp_secret(secret, account_id=owner, key=key, key_version=1)
        second = encrypt_totp_secret(secret, account_id=owner, key=key, key_version=1)
        self.assertNotEqual(first.nonce, second.nonce)
        self.assertNotEqual(first.ciphertext, second.ciphertext)
        self.assertNotIn(secret, repr(first))
        self.assertEqual(decrypt_totp_secret(first, account_id=owner, key=key), secret)
        for wrong in (
            {"account_id": uuid.uuid4(), "key": key},
            {"account_id": owner, "key": secrets.token_bytes(32)},
        ):
            with self.subTest(wrong=wrong["account_id"]), self.assertRaises(ValueError):
                decrypt_totp_secret(first, **wrong)

    def test_tampering_and_bad_inputs_fail_closed(self) -> None:
        key = secrets.token_bytes(32)
        owner = uuid.uuid4()
        encrypted = encrypt_totp_secret(
            generate_totp_secret(), account_id=owner, key=key, key_version=2
        )

        def flip_first(value: str) -> str:
            return ("A" if value[0] != "A" else "B") + value[1:]

        tampered = (
            replace(encrypted, key_version=3),
            replace(encrypted, nonce=flip_first(encrypted.nonce)),
            replace(encrypted, ciphertext=flip_first(encrypted.ciphertext)),
            replace(encrypted, nonce="bad"),
            replace(encrypted, ciphertext="!" * 64),
        )
        for value in tampered:
            with self.subTest(value=value.nonce), self.assertRaises(ValueError):
                decrypt_totp_secret(value, account_id=owner, key=key)
        for invalid_key in (None, b"short", "A" * 32):
            with self.subTest(key=invalid_key), self.assertRaises(ValueError):
                encrypt_totp_secret("A" * 32, account_id=owner, key=invalid_key, key_version=1)
        with self.assertRaises(ValueError):
            encrypt_totp_secret("bad", account_id=owner, key=key, key_version=1)
        with self.assertRaises(ValueError):
            encrypt_totp_secret("A" * 32, account_id=owner, key=key, key_version=0)


if __name__ == "__main__":
    unittest.main()
