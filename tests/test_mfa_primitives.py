"""Standard TOTP vectors and offline recovery-code primitives; no MFA enrollment."""

import base64
import re
import unittest

from fairmount_api.identity.mfa import (
    RECOVERY_ALPHABET,
    generate_recovery_codes,
    generate_totp_secret,
    matched_totp_step,
    recovery_code_digest,
    totp_code,
    verify_recovery_code,
)


class MFAPrimitiveTests(unittest.TestCase):
    def test_rfc_6238_sha1_vectors_truncated_to_six_digits(self) -> None:
        seed = base64.b32encode(b"12345678901234567890").decode("ascii")
        self.assertEqual(totp_code(seed, 59), "287082")
        self.assertEqual(totp_code(seed, 1111111109), "081804")
        self.assertEqual(matched_totp_step(seed, "287082", 59), 1)
        self.assertEqual(matched_totp_step(seed, "287082", 60), 1)
        self.assertIsNone(matched_totp_step(seed, "287082", 90))
        self.assertIsNone(matched_totp_step(seed, "abc123", 59))
        self.assertIsNone(matched_totp_step(seed, "１２３４５６", 59))

    def test_seed_is_random_and_rejects_malformed_inputs(self) -> None:
        first = generate_totp_secret()
        self.assertNotEqual(first, generate_totp_secret())
        self.assertIsNotNone(re.fullmatch(r"[A-Z2-7]{32}", first))
        for seed in ("", "a" * 32, "A" * 31, None):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                totp_code(seed, 59)
        for timestamp in (-1, 1.5, True, None):
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                totp_code(first, timestamp)

    def test_recovery_codes_have_80_bits_and_digest_comparisons(self) -> None:
        codes = generate_recovery_codes()
        self.assertEqual(len(codes), 10)
        self.assertEqual(len(set(codes)), 10)
        for code in codes:
            self.assertIsNotNone(re.fullmatch(rf"[{RECOVERY_ALPHABET}]{{16}}", code))
        first, second = codes[:2]
        digest = recovery_code_digest(first)
        self.assertEqual(len(digest), 64)
        self.assertTrue(verify_recovery_code(first, digest))
        self.assertTrue(verify_recovery_code(first.lower(), digest))
        self.assertTrue(verify_recovery_code(first[:4] + "-" + first[4:], digest))
        for candidate in (second, "wrong", "K" + first[1:], first + "-" * 100, None):
            with self.subTest(candidate=candidate):
                self.assertFalse(verify_recovery_code(candidate, digest))
        self.assertFalse(verify_recovery_code(first, "not-a-digest"))
        with self.assertRaises(ValueError):
            recovery_code_digest("password")


if __name__ == "__main__":
    unittest.main()
