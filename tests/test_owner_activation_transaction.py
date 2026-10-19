"""PostgreSQL-only tests for internal owner activation, expiry and rollback."""

import os
import unittest

from fairmount_api.db.models import Account, AccountCredential, SecurityEvent
from fairmount_api.identity.credentials import verify_password
from fairmount_api.identity.owner_activation import (
    OwnerActivationUnavailable,
    activate_initial_owner,
)
from fairmount_api.identity.owner_bootstrap import bootstrap_owner, reissue_pending_owner_secret
from sqlalchemy import create_engine, func, select, text, update

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class OwnerActivationTransactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(local_database_url(test=True))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()

    def tearDown(self) -> None:
        self.transaction.rollback()
        self.connection.close()

    def test_valid_secret_consumed_once_without_granting_session(self) -> None:
        pending = bootstrap_owner(self.connection)
        owner_id = activate_initial_owner(
            self.connection, pending.secret, "a strong owner passphrase"
        )
        self.assertEqual(owner_id, pending.account_id)
        credential = self.connection.execute(
            select(
                AccountCredential.initial_secret_digest,
                AccountCredential.initial_secret_expires_at,
                AccountCredential.initial_secret_consumed_at,
                AccountCredential.password_hash,
            )
        ).one()
        self.assertIsNone(credential.initial_secret_digest)
        self.assertIsNone(credential.initial_secret_expires_at)
        self.assertIsNotNone(credential.initial_secret_consumed_at)
        self.assertTrue(verify_password("a strong owner passphrase", credential.password_hash))
        self.assertEqual(
            set(self.connection.scalars(select(SecurityEvent.event_type)).all()),
            {"OWNER_BOOTSTRAP_ISSUED", "INITIAL_CREDENTIAL_CONSUMED"},
        )
        with self.assertRaises(OwnerActivationUnavailable):
            activate_initial_owner(self.connection, pending.secret, "another strong passphrase")
        with self.assertRaises(ValueError):
            reissue_pending_owner_secret(self.connection)

    def test_wrong_or_rotated_secret_and_weak_password_do_not_change_state(self) -> None:
        pending = bootstrap_owner(self.connection)
        with self.assertRaises(OwnerActivationUnavailable):
            activate_initial_owner(self.connection, "wrong", "a strong owner passphrase")
        with self.assertRaises(ValueError):
            activate_initial_owner(self.connection, pending.secret, "weak")
        self.assertIsNone(self.connection.scalar(select(AccountCredential.password_hash)))
        rotated = reissue_pending_owner_secret(self.connection)
        with self.assertRaises(OwnerActivationUnavailable):
            activate_initial_owner(self.connection, pending.secret, "a strong owner passphrase")
        self.assertIsNone(self.connection.scalar(select(AccountCredential.password_hash)))
        self.assertEqual(
            activate_initial_owner(self.connection, rotated.secret, "a strong owner passphrase"),
            pending.account_id,
        )

    def test_expired_or_disabled_owner_cannot_activate(self) -> None:
        pending = bootstrap_owner(self.connection)
        self.connection.execute(
            update(AccountCredential.__table__)
            .values(
                initial_secret_issued_at=func.now() - text("interval '2 days'"),
                initial_secret_expires_at=func.now() - text("interval '1 day'"),
            )
        )
        with self.assertRaises(OwnerActivationUnavailable):
            activate_initial_owner(self.connection, pending.secret, "a strong owner passphrase")
        self.assertIsNone(self.connection.scalar(select(AccountCredential.password_hash)))
        rotated = reissue_pending_owner_secret(self.connection)
        self.connection.execute(update(Account.__table__).values(status="DISABLED"))
        with self.assertRaises(OwnerActivationUnavailable):
            activate_initial_owner(self.connection, rotated.secret, "a strong owner passphrase")

    def test_rollback_removes_password_and_activation_audit(self) -> None:
        pending = bootstrap_owner(self.connection)
        with self.assertRaises(RuntimeError), self.connection.begin_nested():
            activate_initial_owner(self.connection, pending.secret, "a strong owner passphrase")
            raise RuntimeError("Simulated failure before commit")
        self.assertIsNone(self.connection.scalar(select(AccountCredential.password_hash)))
        self.assertEqual(
            self.connection.scalars(select(SecurityEvent.event_type)).all(),
            ["OWNER_BOOTSTRAP_ISSUED"],
        )


if __name__ == "__main__":
    unittest.main()
