"""Boundary and Unicode tests for permanent-password validation."""

import unittest

from fairmount_api.identity.credentials import hash_password, verify_password
from fairmount_api.identity.password_policy import validate_new_password


class PasswordPolicyTests(unittest.TestCase):
    def test_accepts_passphrases_without_composition_rules(self) -> None:
        for value in (
            "green ocean sunrise", "this has spaces  ", "uniqué café mot de passe",
            "😀" * 11 + "🎲", "a" * 11 + "b", "a" * 127 + "b",
        ):
            with self.subTest(value=value[:30]):
                self.assertEqual(validate_new_password(value), value)
        value = "  leading spaces preserved  "
        self.assertTrue(verify_password(value, hash_password(value)))
        self.assertFalse(verify_password(value.strip(), hash_password(value)))

    def test_rejects_lengths_controls_whitespace_and_obvious_values(self) -> None:
        invalid = (
            "short", "a" * 129, " " * 12, "\t" * 12, "abc\nlong enough",
            "Password1234", " password1234 ", "123456789012", "qwerty123456",
            "a" * 12, "😀" * 129, "\ud800" * 12, None, 5,
        )
        for value in invalid:
            with self.subTest(value=repr(value)[:40]), self.assertRaises(ValueError):
                validate_new_password(value)
            with self.subTest(value=repr(value)[:40]), self.assertRaises(ValueError):
                hash_password(value)


if __name__ == "__main__":
    unittest.main()
