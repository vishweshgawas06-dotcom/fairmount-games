"""PostgreSQL-only structural checks for pending and activated credential rows."""

import os
import unittest
import uuid

from fairmount_api.db.models import Account, AccountCredential
from fairmount_api.identity.credentials import (
    generate_initial_secret,
    hash_password,
    initial_secret_digest,
)
from sqlalchemy import create_engine, delete, func, insert, select, text, update
from sqlalchemy.exc import IntegrityError

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class AccountCredentialSchemaTests(unittest.TestCase):
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

    def account(self, role="PLAYER"):
        return self.connection.execute(
            insert(Account.__table__).values(role=role).returning(Account.id)
        ).scalar_one()

    def pending(self, account_id, secret="not stored in database"):
        digest = initial_secret_digest(secret)
        self.connection.execute(
            insert(AccountCredential.__table__).values(
                account_id=account_id,
                initial_secret_digest=digest,
                initial_secret_expires_at=func.now() + text("interval '24 hours'"),
            )
        )
        return digest

    def activate(self, account_id) -> None:
        self.connection.execute(
            update(AccountCredential.__table__)
            .where(AccountCredential.account_id == account_id)
            .values(
                initial_secret_digest=None,
                initial_secret_expires_at=None,
                initial_secret_consumed_at=func.now(),
                password_hash=hash_password("a strong permanent passphrase"),
                password_changed_at=func.now(),
            )
        )

    def test_pending_digest_then_one_way_active_state(self) -> None:
        owner = self.account("OWNER")
        secret = generate_initial_secret()
        digest = self.pending(owner, secret)
        self.assertNotEqual(digest, secret)
        self.assertEqual(
            self.connection.scalar(
                select(AccountCredential.initial_secret_digest).where(
                    AccountCredential.account_id == owner
                )
            ),
            digest,
        )
        self.activate(owner)
        self.assertIsNone(
            self.connection.scalar(
                select(AccountCredential.initial_secret_digest).where(
                    AccountCredential.account_id == owner
                )
            )
        )
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                update(AccountCredential.__table__)
                .where(AccountCredential.account_id == owner)
                .values(
                    password_hash=None,
                    password_changed_at=None,
                    initial_secret_digest=digest,
                    initial_secret_expires_at=func.now() + text("interval '24 hours'"),
                    initial_secret_consumed_at=None,
                )
            )
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                delete(AccountCredential.__table__).where(AccountCredential.account_id == owner)
            )
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                update(AccountCredential.__table__)
                .where(AccountCredential.account_id == owner)
                .values(initial_secret_consumed_at=func.now() + text("interval '1 second'"))
            )

    def test_pending_reissue_replaces_digest_and_can_only_last_24_hours(self) -> None:
        agent = self.account("AGENT")
        first = self.pending(agent, "first high entropy secret")
        second = initial_secret_digest("second high entropy secret")
        self.connection.execute(
            update(AccountCredential.__table__)
            .where(AccountCredential.account_id == agent)
            .values(
                initial_secret_digest=second,
                initial_secret_issued_at=func.now(),
                initial_secret_expires_at=func.now() + text("interval '24 hours'"),
            )
        )
        self.assertNotEqual(first, second)
        self.assertEqual(
            self.connection.scalar(
                select(AccountCredential.initial_secret_digest).where(
                    AccountCredential.account_id == agent
                )
            ),
            second,
        )
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                update(AccountCredential.__table__)
                .where(AccountCredential.account_id == agent)
                .values(initial_secret_expires_at=func.now() + text("interval '25 hours'"))
            )

    def test_bad_shapes_or_missing_account_are_rejected(self) -> None:
        invalid = (
            {"initial_secret_digest": "short"},
            {"initial_secret_digest": "A" * 64},
            {"initial_secret_digest": None},
            {"initial_secret_digest": "a" * 64, "password_hash": "$argon2id$bad"},
            {"initial_secret_digest": "a" * 64, "initial_secret_consumed_at": func.now()},
            {"initial_secret_digest": "a" * 64,
             "initial_secret_expires_at": func.now() + text("interval '25 hours'")},
        )
        for changes in invalid:
            with self.subTest(changes=str(changes)[:50]):
                with self.assertRaises(IntegrityError), self.connection.begin_nested():
                    self.connection.execute(
                        insert(AccountCredential.__table__).values(
                            **{
                                "account_id": self.account(),
                                "initial_secret_expires_at": (
                                    func.now() + text("interval '24 hours'")
                                ),
                                **changes,
                            }
                        )
                    )
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.pending(uuid.uuid4())

    def test_only_one_credential_row_per_account(self) -> None:
        player = self.account()
        self.pending(player)
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.pending(player, "another secret")


if __name__ == "__main__":
    unittest.main()
