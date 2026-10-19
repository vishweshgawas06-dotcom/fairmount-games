"""PostgreSQL tests for owner-only encrypted MFA and one-time recovery rows."""

import os
import secrets
import unittest
import uuid

from fairmount_api.db.models import Account, OwnerMFA, OwnerRecoveryCode
from fairmount_api.identity.mfa import (
    generate_recovery_codes,
    generate_totp_secret,
    recovery_code_digest,
)
from fairmount_api.identity.mfa_encryption import encrypt_totp_secret
from sqlalchemy import create_engine, delete, func, insert, select, text, update
from sqlalchemy.exc import IntegrityError

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class OwnerMFASchemaTests(unittest.TestCase):
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

    def account(self, role="OWNER"):
        return self.connection.execute(
            insert(Account.__table__).values(role=role).returning(Account.id)
        ).scalar_one()

    def factor(self, account_id, **overrides):
        encrypted = encrypt_totp_secret(
            generate_totp_secret(),
            account_id=account_id,
            key=secrets.token_bytes(32),
            key_version=1,
        )
        values = {
            "account_id": account_id,
            "key_version": encrypted.key_version,
            "nonce": encrypted.nonce,
            "ciphertext": encrypted.ciphertext,
            **overrides,
        }
        self.connection.execute(insert(OwnerMFA.__table__).values(**values))

    def test_only_owner_factor_and_ten_hashed_recovery_codes(self) -> None:
        owner = self.account()
        self.factor(owner)
        codes = generate_recovery_codes()
        for code in codes:
            self.connection.execute(
                insert(OwnerRecoveryCode.__table__).values(
                    owner_account_id=owner, digest=recovery_code_digest(code)
                )
            )
        self.connection.execute(
            update(OwnerMFA.__table__)
            .where(OwnerMFA.account_id == owner)
            .values(confirmed_at=func.now(), last_accepted_step=1234)
        )
        self.assertEqual(
            self.connection.scalar(
                select(OwnerMFA.last_accepted_step).where(OwnerMFA.account_id == owner)
            ),
            1234,
        )
        self.assertEqual(
            self.connection.scalar(
                select(func.count())
                .select_from(OwnerRecoveryCode.__table__)
                .where(OwnerRecoveryCode.owner_account_id == owner)
            ),
            10,
        )
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                update(Account.__table__).where(Account.id == owner).values(role="AGENT")
            )

    def test_non_owner_or_malformed_factor_rejected(self) -> None:
        player = self.account("PLAYER")
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.factor(player)
        owner = self.account()
        for changes in (
            {"key_version": 0},
            {"nonce": "bad"},
            {"ciphertext": "!" * 64},
            {"account_role": "PLAYER"},
            {"last_accepted_step": -1},
            {"last_accepted_step": 1},
            {"confirmed_at": func.now() - text("interval '1 second'")},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(IntegrityError), self.connection.begin_nested():
                    self.factor(owner, **changes)
        self.factor(owner)
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.factor(owner)

    def test_recovery_code_digest_unique_and_consumable_once(self) -> None:
        owner = self.account()
        self.factor(owner)
        digest = recovery_code_digest(generate_recovery_codes()[0])
        code_id = self.connection.execute(
            insert(OwnerRecoveryCode.__table__)
            .values(owner_account_id=owner, digest=digest)
            .returning(OwnerRecoveryCode.id)
        ).scalar_one()
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                insert(OwnerRecoveryCode.__table__).values(owner_account_id=owner, digest=digest)
            )
        for values in ({"digest": "bad"}, {"owner_account_id": uuid.uuid4()}):
            with self.subTest(values=values):
                with self.assertRaises(IntegrityError), self.connection.begin_nested():
                    self.connection.execute(
                        insert(OwnerRecoveryCode.__table__).values(
                            **{"owner_account_id": owner, "digest": "b" * 64, **values}
                        )
                    )
        self.connection.execute(
            update(OwnerRecoveryCode.__table__)
            .where(OwnerRecoveryCode.id == code_id)
            .values(consumed_at=func.now())
        )
        for changes in ({"consumed_at": None}, {"consumed_at": func.now()}, {"digest": "c" * 64}):
            with self.subTest(changes=changes):
                with self.assertRaises(IntegrityError), self.connection.begin_nested():
                    self.connection.execute(
                        update(OwnerRecoveryCode.__table__)
                        .where(OwnerRecoveryCode.id == code_id)
                        .values(**changes)
                    )
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                delete(OwnerRecoveryCode.__table__).where(OwnerRecoveryCode.id == code_id)
            )
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(text("TRUNCATE owner_recovery_codes"))
        self.assertIsNotNone(
            self.connection.scalar(
                select(OwnerRecoveryCode.consumed_at).where(OwnerRecoveryCode.id == code_id)
            )
        )


if __name__ == "__main__":
    unittest.main()
