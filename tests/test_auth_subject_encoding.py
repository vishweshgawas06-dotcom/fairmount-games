"""Malformed escaped JSON subjects must not bypass authentication accounting."""

import unittest

from fairmount_api.identity.auth_attempts import _digests


class AuthSubjectEncodingTests(unittest.TestCase):
    def test_unencodable_identifiers_share_the_invalid_subject_bucket(self):
        for surface in ("OWNER_LOGIN", "MEMBER_LOGIN", "OWNER_MFA", "MEMBER_ACTIVATION"):
            invalid = _digests(surface, "", "203.0.113.1", b"a" * 32)
            for identifier in ("\ud800", "PLAYER:\udfff", "AGENT:bad\ud800text"):
                with self.subTest(surface=surface, identifier=repr(identifier)):
                    self.assertEqual(
                        _digests(surface, identifier, "203.0.113.1", b"a" * 32), invalid
                    )
