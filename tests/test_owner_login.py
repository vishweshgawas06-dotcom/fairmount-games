"""PostgreSQL owner password+MFA session issuance tests, without an HTTP route."""

import os
import secrets
import unittest
from types import MappingProxyType

from fairmount_api.db.models import AccountSession, OwnerRecoveryCode, SecurityEvent
from fairmount_api.identity.mfa import totp_code
from fairmount_api.identity.mfa_keys import MFAKeyring
from fairmount_api.identity.owner_activation import activate_initial_owner
from fairmount_api.identity.owner_bootstrap import bootstrap_owner
from fairmount_api.identity.owner_login import OwnerLoginUnavailable, issue_owner_session
from fairmount_api.identity.owner_mfa_enrollment import (
    begin_owner_mfa_enrollment,
    confirm_owner_mfa_enrollment,
)
from fairmount_api.identity.session_validation import resolve_session
from sqlalchemy import create_engine, func, select

from infrastructure.local_db_url import local_database_url

PASSWORD = "a strong private owner passphrase"


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class OwnerLoginTests(unittest.TestCase):
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
        self.owner_id = activate_initial_owner(self.connection, pending_owner.secret, PASSWORD)
        pending = begin_owner_mfa_enrollment(self.connection, self.keyring)
        now = self.connection.scalar(select(func.clock_timestamp()))
        confirmed = confirm_owner_mfa_enrollment(
            self.connection, totp_code(pending.secret, int(now.timestamp())), self.keyring
        )
        self.codes = confirmed.recovery_codes

    def tearDown(self) -> None:
        self.transaction.rollback()
        self.connection.close()

    def count(self, model):
        return self.connection.scalar(select(func.count()).select_from(model))

    def test_wrong_identifier_password_or_factor_never_consume_or_revoke(self) -> None:
        first = issue_owner_session(
            self.connection, "owner", PASSWORD, "recovery", self.codes[0], self.keyring
        )
        for identifier, password, code in (
            ("Owner", PASSWORD, self.codes[1]),
            ("owner", "a wrong private owner passphrase", self.codes[1]),
            ("owner", PASSWORD, "INVALID"),
        ):
            with self.assertRaises(OwnerLoginUnavailable):
                issue_owner_session(
                    self.connection, identifier, password, "recovery", code, self.keyring
                )
        self.assertEqual(
            self.connection.scalar(
                select(func.count())
                .select_from(OwnerRecoveryCode)
                .where(OwnerRecoveryCode.consumed_at.is_not(None))
            ),
            1,
        )
        self.assertIsNone(
            self.connection.scalar(
                select(AccountSession.revoked_at).where(AccountSession.id == first.session_id)
            )
        )
        self.assertEqual(self.count(AccountSession), 1)
        self.assertEqual(resolve_session(self.connection, first.token).account_id, self.owner_id)

    def test_new_login_revokes_old_only_after_both_factors_and_never_persists_token(self) -> None:
        first = issue_owner_session(
            self.connection, "owner", PASSWORD, "recovery", self.codes[0], self.keyring
        )
        self.assertNotIn(first.token, repr(first))
        self.assertEqual(len(first.token), 43)
        self.assertNotEqual(
            self.connection.scalar(
                select(AccountSession.token_digest).where(AccountSession.id == first.session_id)
            ),
            first.token,
        )
        second = issue_owner_session(
            self.connection, "owner", PASSWORD, "recovery", self.codes[1], self.keyring
        )
        self.assertNotEqual(first.token, second.token)
        self.assertIsNone(resolve_session(self.connection, first.token))
        self.assertEqual(resolve_session(self.connection, second.token).account_id, self.owner_id)
        self.assertEqual(self.count(AccountSession), 2)
        self.assertEqual(
            self.connection.scalar(
                select(func.count())
                .select_from(AccountSession)
                .where(AccountSession.revoked_at.is_(None))
            ),
            1,
        )
        self.assertEqual(
            self.connection.scalar(
                select(func.count())
                .select_from(SecurityEvent)
                .where(SecurityEvent.event_type == "OWNER_SESSION_STARTED")
            ),
            2,
        )

    def test_rollback_undoes_factor_consumption_session_and_audit(self) -> None:
        before = self.count(SecurityEvent)
        with self.assertRaises(RuntimeError), self.connection.begin_nested():
            issue_owner_session(
                self.connection, "owner", PASSWORD, "recovery", self.codes[0], self.keyring
            )
            raise RuntimeError("Simulated failure before commit or token delivery")
        self.assertEqual(self.count(AccountSession), 0)
        self.assertEqual(self.count(SecurityEvent), before)
        self.assertEqual(
            self.connection.scalar(
                select(func.count())
                .select_from(OwnerRecoveryCode)
                .where(OwnerRecoveryCode.consumed_at.is_not(None))
            ),
            0,
        )
        issued = issue_owner_session(
            self.connection, "owner", PASSWORD, "recovery", self.codes[0], self.keyring
        )
        self.assertEqual(issued.account_id, self.owner_id)


if __name__ == "__main__":
    unittest.main()
