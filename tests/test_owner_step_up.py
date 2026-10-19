"""PostgreSQL owner MFA ten-minute recency and atomic step-up tests."""

import os
import secrets
import unittest
from types import MappingProxyType

from fairmount_api.db.models import AccountSession, OwnerRecoveryCode, SecurityEvent
from fairmount_api.identity.mfa import totp_code
from fairmount_api.identity.mfa_keys import MFAKeyring
from fairmount_api.identity.owner_activation import activate_initial_owner
from fairmount_api.identity.owner_bootstrap import bootstrap_owner
from fairmount_api.identity.owner_login import issue_owner_session
from fairmount_api.identity.owner_mfa_enrollment import (
    begin_owner_mfa_enrollment,
    confirm_owner_mfa_enrollment,
)
from fairmount_api.identity.owner_mfa_verification import OwnerMFAProofUnavailable
from fairmount_api.identity.owner_step_up import require_recent_owner_mfa, step_up_owner_session
from sqlalchemy import create_engine, func, select, text, update

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class OwnerStepUpTests(unittest.TestCase):
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
        pending_factor = begin_owner_mfa_enrollment(self.connection, self.keyring)
        now = self.connection.scalar(select(func.clock_timestamp()))
        confirmed = confirm_owner_mfa_enrollment(
            self.connection,
            totp_code(pending_factor.secret, int(now.timestamp())),
            self.keyring,
        )
        self.codes = confirmed.recovery_codes
        self.issued = issue_owner_session(
            self.connection,
            "owner",
            "a strong private owner passphrase",
            "recovery",
            self.codes[0],
            self.keyring,
        )

    def tearDown(self) -> None:
        self.transaction.rollback()
        self.connection.close()

    def verified_events(self):
        return self.connection.scalar(
            select(func.count())
            .select_from(SecurityEvent)
            .where(SecurityEvent.event_type == "OWNER_MFA_VERIFIED")
        )

    def consumed_count(self):
        return self.connection.scalar(
            select(func.count())
            .select_from(OwnerRecoveryCode)
            .where(OwnerRecoveryCode.consumed_at.is_not(None))
        )

    def test_fresh_then_stale_then_step_up_on_same_session(self) -> None:
        self.assertEqual(
            require_recent_owner_mfa(self.connection, self.issued.token).account_id,
            self.owner_id,
        )
        self.connection.execute(
            update(AccountSession.__table__)
            .where(AccountSession.id == self.issued.session_id)
            .values(
                issued_at=func.now() - text("interval '11 minutes'"),
                mfa_verified_at=func.now() - text("interval '11 minutes'"),
                absolute_expires_at=func.now() + text("interval '7 hours 49 minutes'"),
            )
        )
        self.assertIsNone(require_recent_owner_mfa(self.connection, self.issued.token))
        before = self.verified_events()
        session = step_up_owner_session(
            self.connection, self.issued.token, "recovery", self.codes[1], self.keyring
        )
        self.assertEqual(session.session_id, self.issued.session_id)
        self.assertEqual(self.verified_events(), before + 1)
        self.assertEqual(self.consumed_count(), 2)
        self.assertIsNotNone(require_recent_owner_mfa(self.connection, self.issued.token))
        self.assertIsNone(require_recent_owner_mfa(self.connection, "invalid"))

    def test_step_up_replay_failure_and_rollback(self) -> None:
        before = self.verified_events()
        with self.assertRaises(RuntimeError), self.connection.begin_nested():
            step_up_owner_session(
                self.connection, self.issued.token, "recovery", self.codes[1], self.keyring
            )
            raise RuntimeError("Simulated rollback before sensitive action")
        self.assertEqual(self.consumed_count(), 1)
        self.assertEqual(self.verified_events(), before)
        with self.assertRaises(OwnerMFAProofUnavailable), self.connection.begin_nested():
            step_up_owner_session(
                self.connection, "invalid", "recovery", self.codes[1], self.keyring
            )
        step_up_owner_session(
            self.connection, self.issued.token, "recovery", self.codes[1], self.keyring
        )
        with self.assertRaises(OwnerMFAProofUnavailable), self.connection.begin_nested():
            step_up_owner_session(
                self.connection, self.issued.token, "recovery", self.codes[1], self.keyring
            )
        self.assertEqual(self.consumed_count(), 2)
        self.assertEqual(self.verified_events(), before + 1)


if __name__ == "__main__":
    unittest.main()
