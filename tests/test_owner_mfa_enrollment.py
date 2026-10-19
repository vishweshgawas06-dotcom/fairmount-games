"""PostgreSQL-only internal owner MFA enrollment transaction tests."""

import os
import secrets
import unittest
from types import MappingProxyType

from fairmount_api.db.models import Account, OwnerMFA, OwnerRecoveryCode, SecurityEvent
from fairmount_api.identity.mfa import recovery_code_digest, totp_code
from fairmount_api.identity.mfa_keys import MFAKeyring
from fairmount_api.identity.owner_activation import activate_initial_owner
from fairmount_api.identity.owner_bootstrap import bootstrap_owner
from fairmount_api.identity.owner_mfa_enrollment import (
    OwnerMFAUnavailable,
    begin_owner_mfa_enrollment,
    confirm_owner_mfa_enrollment,
)
from sqlalchemy import create_engine, func, select, update

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class OwnerMFAEnrollmentTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        self.transaction.rollback()
        self.connection.close()

    def activated_owner(self):
        pending = bootstrap_owner(self.connection)
        activate_initial_owner(self.connection, pending.secret, "an excellent owner passphrase")
        return pending.account_id

    def current_code(self, secret: str) -> str:
        now = self.connection.scalar(select(func.clock_timestamp()))
        return totp_code(secret, int(now.timestamp()))

    def test_confirm_enrollment_stores_only_ciphertext_and_ten_digests(self) -> None:
        owner = self.activated_owner()
        pending = begin_owner_mfa_enrollment(self.connection, self.keyring)
        self.assertEqual(pending.account_id, owner)
        self.assertNotIn(pending.secret, repr(pending))
        factor = self.connection.execute(select(OwnerMFA.ciphertext, OwnerMFA.confirmed_at)).one()
        self.assertNotIn(pending.secret, factor.ciphertext)
        self.assertIsNone(factor.confirmed_at)
        result = confirm_owner_mfa_enrollment(
            self.connection, self.current_code(pending.secret), self.keyring
        )
        self.assertEqual(result.account_id, owner)
        self.assertNotIn(result.recovery_codes[0], repr(result))
        self.assertEqual(len(set(result.recovery_codes)), 10)
        stored = set(self.connection.scalars(select(OwnerRecoveryCode.digest)).all())
        self.assertEqual(stored, {recovery_code_digest(code) for code in result.recovery_codes})
        last_step = self.connection.scalar(select(OwnerMFA.last_accepted_step))
        self.assertIsNotNone(last_step)
        events = set(self.connection.scalars(select(SecurityEvent.event_type)).all())
        self.assertIn("OWNER_MFA_ENROLLED", events)
        with self.assertRaises(OwnerMFAUnavailable):
            confirm_owner_mfa_enrollment(
                self.connection, self.current_code(pending.secret), self.keyring
            )
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(OwnerRecoveryCode)), 10
        )

    def test_unactivated_owner_cannot_begin(self) -> None:
        bootstrap_owner(self.connection)
        with self.assertRaises(OwnerMFAUnavailable):
            begin_owner_mfa_enrollment(self.connection, self.keyring)

    def test_wrong_code_and_rollback_leave_factor_unconfirmed(self) -> None:
        self.activated_owner()
        pending = begin_owner_mfa_enrollment(self.connection, self.keyring)
        code = self.current_code(pending.secret)
        with self.assertRaises(OwnerMFAUnavailable):
            confirm_owner_mfa_enrollment(self.connection, "ABCDEF", self.keyring)
        self.assertIsNone(self.connection.scalar(select(OwnerMFA.confirmed_at)))
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(OwnerRecoveryCode)), 0
        )
        with self.assertRaises(RuntimeError), self.connection.begin_nested():
            confirm_owner_mfa_enrollment(self.connection, code, self.keyring)
            raise RuntimeError("Simulated delivery failure before commit")
        self.assertIsNone(self.connection.scalar(select(OwnerMFA.confirmed_at)))
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(OwnerRecoveryCode)), 0
        )

    def test_disabled_owner_cannot_begin_or_confirm(self) -> None:
        owner = self.activated_owner()
        pending = begin_owner_mfa_enrollment(self.connection, self.keyring)
        self.connection.execute(
            update(Account.__table__).where(Account.id == owner).values(status="DISABLED")
        )
        with self.assertRaises(OwnerMFAUnavailable):
            confirm_owner_mfa_enrollment(
                self.connection, self.current_code(pending.secret), self.keyring
            )
        self.assertIsNone(self.connection.scalar(select(OwnerMFA.confirmed_at)))


if __name__ == "__main__":
    unittest.main()
