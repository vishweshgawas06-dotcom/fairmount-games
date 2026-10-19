"""PostgreSQL session logout and audit tests; HTTP/CSRF boundary remains closed."""

import os
import secrets
import unittest
from types import MappingProxyType

from fairmount_api.db.models import Account, AccountSession, SecurityEvent
from fairmount_api.identity.mfa import totp_code
from fairmount_api.identity.mfa_keys import MFAKeyring
from fairmount_api.identity.owner_activation import activate_initial_owner
from fairmount_api.identity.owner_bootstrap import bootstrap_owner
from fairmount_api.identity.owner_login import issue_owner_session
from fairmount_api.identity.owner_mfa_enrollment import (
    begin_owner_mfa_enrollment,
    confirm_owner_mfa_enrollment,
)
from fairmount_api.identity.session_logout import revoke_presented_session
from fairmount_api.identity.session_validation import resolve_session
from sqlalchemy import create_engine, func, select, text, update

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class SessionLogoutTests(unittest.TestCase):
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
        pending = bootstrap_owner(self.connection)
        self.owner_id = activate_initial_owner(
            self.connection, pending.secret, "a strong private owner passphrase"
        )
        factor = begin_owner_mfa_enrollment(self.connection, self.keyring)
        now = self.connection.scalar(select(func.clock_timestamp()))
        confirmed = confirm_owner_mfa_enrollment(
            self.connection, totp_code(factor.secret, int(now.timestamp())), self.keyring
        )
        self.issued = issue_owner_session(
            self.connection,
            "owner",
            "a strong private owner passphrase",
            "recovery",
            confirmed.recovery_codes[0],
            self.keyring,
        )

    def tearDown(self) -> None:
        self.transaction.rollback()
        self.connection.close()

    def logout_events(self):
        return self.connection.scalar(
            select(func.count())
            .select_from(SecurityEvent)
            .where(SecurityEvent.event_type == "SESSION_REVOKED")
        )

    def test_logout_invalidates_only_once_and_does_not_persist_token(self) -> None:
        for token in ("", "invalid", "-" * 43, None, 42):
            self.assertFalse(revoke_presented_session(self.connection, token))
        self.assertEqual(self.logout_events(), 0)
        self.assertTrue(revoke_presented_session(self.connection, self.issued.token))
        self.assertIsNone(resolve_session(self.connection, self.issued.token))
        self.assertFalse(revoke_presented_session(self.connection, self.issued.token))
        self.assertEqual(self.logout_events(), 1)
        self.assertNotIn(
            self.issued.token,
            repr(
                self.connection.execute(
                    select(SecurityEvent).where(SecurityEvent.event_type == "SESSION_REVOKED")
                ).all()
            ),
        )

    def test_rollback_restores_session_and_audit(self) -> None:
        with self.assertRaises(RuntimeError), self.connection.begin_nested():
            self.assertTrue(revoke_presented_session(self.connection, self.issued.token))
            raise RuntimeError("Simulated failure before commit")
        self.assertEqual(self.logout_events(), 0)
        self.assertIsNotNone(resolve_session(self.connection, self.issued.token))

    def test_expired_session_can_still_be_logged_out(self) -> None:
        self.connection.execute(
            update(AccountSession.__table__)
            .where(AccountSession.id == self.issued.session_id)
            .values(
                issued_at=func.now() - text("interval '1 hour'"),
                mfa_verified_at=func.now() - text("interval '1 hour'"),
                last_seen_at=func.now() - text("interval '16 minutes'"),
                idle_expires_at=func.now() - text("interval '1 minute'"),
                absolute_expires_at=func.now() + text("interval '7 hours'"),
            )
        )
        self.assertTrue(revoke_presented_session(self.connection, self.issued.token))
        self.assertEqual(self.logout_events(), 1)
        self.assertIsNone(resolve_session(self.connection, self.issued.token))

    def test_disabled_session_is_already_revoked_by_database(self) -> None:
        self.connection.execute(
            update(Account.__table__).where(Account.id == self.owner_id).values(status="DISABLED")
        )
        self.assertFalse(revoke_presented_session(self.connection, self.issued.token))
        self.assertEqual(self.logout_events(), 0)
        self.assertIsNone(resolve_session(self.connection, self.issued.token))


if __name__ == "__main__":
    unittest.main()
