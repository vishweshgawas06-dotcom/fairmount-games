"""Credential primitives; no accounts, sessions or activation endpoints are created."""

import hashlib
import re
import unittest

from fairmount_api.identity.credentials import (
    generate_initial_secret,
    hash_password,
    initial_secret_digest,
    verify_initial_secret,
    verify_password,
)


class CredentialPrimitiveTests(unittest.TestCase):
    def test_password_hashing_uses_salted_argon2id(self) -> None:
        first = hash_password("correct horse battery staple")
        second = hash_password("correct horse battery staple")
        self.assertTrue(first.startswith("$argon2id$"))
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("correct horse battery staple", first))
        self.assertTrue(verify_password("correct horse battery staple", second))
        self.assertFalse(verify_password("wrong", first))

    def test_invalid_password_inputs_and_hashes_fail_closed(self) -> None:
        for value in ("", None, 5, "password", "password1234"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                hash_password(value)
        for invalid in ("", "not-a-hash", "$argon2i$v=19$m=65536,t=3,p=4$bad$bad", None):
            with self.subTest(invalid=invalid):
                self.assertFalse(verify_password("password", invalid))
        self.assertFalse(verify_password(None, hash_password("a valid long passphrase")))

    def test_random_initial_secret_and_digest(self) -> None:
        first = generate_initial_secret()
        second = generate_initial_secret()
        self.assertNotEqual(first, second)
        self.assertIsNotNone(re.fullmatch(r"[A-Za-z0-9_-]{43}", first))
        digest = initial_secret_digest(first)
        self.assertEqual(digest, hashlib.sha256(first.encode()).hexdigest())
        self.assertNotIn(first, digest)
        self.assertTrue(verify_initial_secret(first, digest))
        self.assertFalse(verify_initial_secret(second, digest))
        self.assertFalse(verify_initial_secret(first, "bad"))
        self.assertFalse(verify_initial_secret(first * 10, digest))
        self.assertFalse(verify_initial_secret(None, digest))
        with self.assertRaises(ValueError):
            initial_secret_digest("")


if __name__ == "__main__":
    unittest.main()
