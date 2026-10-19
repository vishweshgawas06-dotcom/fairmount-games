"""Internal PostgreSQL owner MFA proof and rollback tests; no login route."""

import os
import secrets
import unittest
from types import MappingProxyType

from fairmount_api.db.models import Account, OwnerMFA, OwnerRecoveryCode, SecurityEvent
from fairmount_api.identity.mfa import totp_code
from fairmount_api.identity.mfa_keys import MFAKeyring
from fairmount_api.identity.owner_activation import activate_initial_owner
from fairmount_api.identity.owner_bootstrap import bootstrap_owner
from fairmount_api.identity.owner_mfa_enrollment import (
    begin_owner_mfa_enrollment,
    confirm_owner_mfa_enrollment,
)
from fairmount_api.identity.owner_mfa_verification import (
    OwnerMFAProofUnavailable,
    verify_owner_mfa,
)
from sqlalchemy import create_engine, func, select, update

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class OwnerMFAVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(local_database_url(test=True))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.keyring = MFAKeyring(1, MappingProxyType({1: secrets.token_bytes(32)}))
        pending_owner = bootstrap_owner(self.connection)
        self.owner_id = activate_initial_owner(
            self.connection, pending_owner.secret, "a strong private owner passphrase"
        )

    def tearDown(self) -> None:
        self.transaction.rollback()
        self.connection.close()

    def enroll(self):
        pending = begin_owner_mfa_enrollment(self.connection, self.keyring)
        now = self.connection.scalar(select(func.clock_timestamp()))
        result = confirm_owner_mfa_enrollment(
            self.connection, totp_code(pending.secret, int(now.timestamp())), self.keyring
        )
        return pending.secret, result.recovery_codes

    def verified_events(self):
        return self.connection.scalar(
            select(func.count())
            .select_from(SecurityEvent)
            .where(SecurityEvent.event_type == "OWNER_MFA_VERIFIED")
        )

    def test_unconfirmed_and_disabled_owner_cannot_verify(self) -> None:
        begin_owner_mfa_enrollment(self.connection, self.keyring)
        with self.assertRaises(OwnerMFAProofUnavailable):
            verify_owner_mfa(self.connection, self.owner_id, "totp", "123456", self.keyring)
        self.assertEqual(self.verified_events(), 0)
        self.assertIsNone(self.connection.scalar(select(OwnerMFA.confirmed_at)))

    def test_totp_step_single_use_wrong_code_and_key_fail_closed(self) -> None:
        secret, _ = self.enroll()
        previous_step = self.connection.scalar(select(OwnerMFA.last_accepted_step))
        next_code = totp_code(secret, (previous_step + 1) * 30)
        wrong_keyring = MFAKeyring(1, MappingProxyType({1: secrets.token_bytes(32)}))
        for supplied_keyring, code in (
            (self.keyring, "not a code"),
            (wrong_keyring, next_code),
        ):
            with self.assertRaises(OwnerMFAProofUnavailable):
                verify_owner_mfa(self.connection, self.owner_id, "totp", code, supplied_keyring)
        self.assertEqual(self.connection.scalar(select(OwnerMFA.last_accepted_step)), previous_step)
        when = verify_owner_mfa(self.connection, self.owner_id, "totp", next_code, self.keyring)
        self.assertIsNotNone(when.tzinfo)
        self.assertEqual(
            self.connection.scalar(select(OwnerMFA.last_accepted_step)), previous_step + 1
        )
        self.assertEqual(self.verified_events(), 1)
        with self.assertRaises(OwnerMFAProofUnavailable):
            verify_owner_mfa(self.connection, self.owner_id, "totp", next_code, self.keyring)
        self.assertEqual(self.verified_events(), 1)

    def test_totp_rollback_restores_step_and_event(self) -> None:
        secret, _ = self.enroll()
        previous_step = self.connection.scalar(select(OwnerMFA.last_accepted_step))
        next_code = totp_code(secret, (previous_step + 1) * 30)
        with self.assertRaises(RuntimeError), self.connection.begin_nested():
            verify_owner_mfa(self.connection, self.owner_id, "totp", next_code, self.keyring)
            raise RuntimeError("Simulated failure before commit")
        self.assertEqual(self.connection.scalar(select(OwnerMFA.last_accepted_step)), previous_step)
        self.assertEqual(self.verified_events(), 0)
        verify_owner_mfa(self.connection, self.owner_id, "totp", next_code, self.keyring)
        self.assertEqual(self.verified_events(), 1)

    def test_recovery_code_consumed_once_and_rollback_safe(self) -> None:
        _, codes = self.enroll()
        code = codes[0]
        with self.assertRaises(RuntimeError), self.connection.begin_nested():
            verify_owner_mfa(self.connection, self.owner_id, "recovery", code, self.keyring)
            raise RuntimeError("Simulated failure before commit")
        self.assertEqual(self.verified_events(), 0)
        self.assertEqual(
            self.connection.scalar(
                select(func.count())
                .select_from(OwnerRecoveryCode)
                .where(OwnerRecoveryCode.consumed_at.is_not(None))
            ),
            0,
        )
        verified_at = verify_owner_mfa(
            self.connection, self.owner_id, "recovery", code.lower(), self.keyring
        )
        self.assertIsNotNone(verified_at.tzinfo)
        self.assertEqual(self.verified_events(), 1)
        with self.assertRaises(OwnerMFAProofUnavailable):
            verify_owner_mfa(self.connection, self.owner_id, "recovery", code, self.keyring)
        with self.assertRaises(OwnerMFAProofUnavailable):
            verify_owner_mfa(self.connection, self.owner_id, "recovery", "ABCD", self.keyring)
        self.assertEqual(self.verified_events(), 1)
        self.assertEqual(
            self.connection.scalar(
                select(func.count())
                .select_from(OwnerRecoveryCode)
                .where(OwnerRecoveryCode.consumed_at.is_not(None))
            ),
            1,
        )

    def test_disabled_owner_cannot_consume_recovery_code(self) -> None:
        _, codes = self.enroll()
        self.connection.execute(
            update(Account.__table__).where(Account.id == self.owner_id).values(status="DISABLED")
        )
        with self.assertRaises(OwnerMFAProofUnavailable):
            verify_owner_mfa(self.connection, self.owner_id, "recovery", codes[0], self.keyring)
        self.assertEqual(self.verified_events(), 0)
        self.assertEqual(
            self.connection.scalar(
                select(func.count())
                .select_from(OwnerRecoveryCode)
                .where(OwnerRecoveryCode.consumed_at.is_not(None))
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()
