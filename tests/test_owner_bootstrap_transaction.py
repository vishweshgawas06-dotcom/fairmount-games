"""PostgreSQL-only transactional tests for internal owner bootstrap/reissue."""

import os
import secrets
import unittest

from fairmount_api.db.models import Account, AccountCredential, OwnerMFA, SecurityEvent
from fairmount_api.identity.credentials import hash_password, initial_secret_digest
from fairmount_api.identity.mfa import generate_totp_secret
from fairmount_api.identity.mfa_encryption import encrypt_totp_secret
from fairmount_api.identity.owner_bootstrap import bootstrap_owner, reissue_pending_owner_secret
from sqlalchemy import create_engine, func, insert, select, update

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class OwnerBootstrapTransactionTests(unittest.TestCase):
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

    def events(self):
        return self.connection.scalars(select(SecurityEvent.event_type)).all()

    def test_bootstrap_and_reissue_replace_digest_and_audit(self) -> None:
        first = bootstrap_owner(self.connection)
        self.assertNotIn(first.secret, repr(first))
        self.assertEqual(len(first.secret), 43)
        self.assertEqual(self.connection.scalar(select(Account.role)), "OWNER")
        self.assertEqual(
            self.connection.scalar(select(AccountCredential.initial_secret_digest)),
            initial_secret_digest(first.secret),
        )
        self.assertEqual(self.events(), ["OWNER_BOOTSTRAP_ISSUED"])
        second = reissue_pending_owner_secret(self.connection)
        self.assertEqual(first.account_id, second.account_id)
        self.assertNotEqual(first.secret, second.secret)
        self.assertEqual(
            self.connection.scalar(select(AccountCredential.initial_secret_digest)),
            initial_secret_digest(second.secret),
        )
        self.assertEqual(
            set(self.events()), {"OWNER_BOOTSTRAP_ISSUED", "OWNER_BOOTSTRAP_REISSUED"}
        )
        with self.assertRaises(ValueError):
            bootstrap_owner(self.connection)
        self.assertEqual(len(self.events()), 2)

    def test_rollback_never_leaves_partial_owner_or_audit(self) -> None:
        with self.assertRaises(RuntimeError), self.connection.begin_nested():
            bootstrap_owner(self.connection)
            raise RuntimeError("Simulated failure before commit")
        self.assertIsNone(self.connection.scalar(select(Account.id)))
        self.assertIsNone(self.connection.scalar(select(AccountCredential.account_id)))
        self.assertIsNone(self.connection.scalar(select(SecurityEvent.id)))

    def test_reissue_rejects_disabled_or_activated_owner(self) -> None:
        owner = bootstrap_owner(self.connection).account_id
        self.connection.execute(
            update(Account.__table__).where(Account.id == owner).values(status="DISABLED")
        )
        with self.assertRaises(ValueError):
            reissue_pending_owner_secret(self.connection)
        self.connection.execute(
            update(Account.__table__).where(Account.id == owner).values(status="ENABLED")
        )
        self.connection.execute(
            update(AccountCredential.__table__)
            .where(AccountCredential.account_id == owner)
            .values(
                initial_secret_digest=None,
                initial_secret_expires_at=None,
                initial_secret_consumed_at=func.now(),
                password_hash=hash_password("a secure owner passphrase"),
                password_changed_at=func.now(),
            )
        )
        with self.assertRaises(ValueError):
            reissue_pending_owner_secret(self.connection)
        self.assertEqual(self.events(), ["OWNER_BOOTSTRAP_ISSUED"])

    def test_reissue_rejects_started_mfa_even_if_credential_pending(self) -> None:
        owner = bootstrap_owner(self.connection).account_id
        encrypted = encrypt_totp_secret(
            generate_totp_secret(), account_id=owner, key=secrets.token_bytes(32), key_version=1
        )
        self.connection.execute(
            insert(OwnerMFA.__table__).values(
                account_id=owner,
                key_version=encrypted.key_version,
                nonce=encrypted.nonce,
                ciphertext=encrypted.ciphertext,
            )
        )
        with self.assertRaises(ValueError):
            reissue_pending_owner_secret(self.connection)
        self.assertEqual(self.events(), ["OWNER_BOOTSTRAP_ISSUED"])


if __name__ == "__main__":
    unittest.main()
