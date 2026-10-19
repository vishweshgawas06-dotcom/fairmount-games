"""PostgreSQL cross-table login-role constraint; no registration API exists."""

import os
import unittest
import uuid

from fairmount_api.db.models import Account, PrivateIdentity
from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.exc import IntegrityError

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class IdentityRoleBindingTests(unittest.TestCase):
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

    def account(self, role: str):
        return self.connection.execute(
            insert(Account.__table__).values(role=role).returning(Account.id)
        ).scalar_one()

    def identity(self, account_id, kind: str | None, identifier: str | None) -> None:
        self.connection.execute(
            insert(PrivateIdentity.__table__).values(
                account_id=account_id, login_kind=kind, login_identifier=identifier
            )
        )

    def test_matching_roles_and_nullable_identity(self) -> None:
        owner = self.account("OWNER")
        agent = self.account("AGENT")
        player = self.account("PLAYER")
        self.identity(owner, None, None)
        self.identity(agent, "AGENT", "agt-aaaaaaaaaa")
        self.identity(player, "PLAYER", "alice")
        self.assertEqual(
            self.connection.scalar(
                select(PrivateIdentity.login_identifier).where(PrivateIdentity.account_id == player)
            ),
            "alice",
        )
        empty = self.account("PLAYER")
        self.identity(empty, None, None)
        self.connection.execute(
            update(PrivateIdentity.__table__)
            .where(PrivateIdentity.account_id == empty)
            .values(login_kind="PLAYER", login_identifier="bob")
        )

    def test_insert_rejects_mismatched_roles(self) -> None:
        cases = (
            ("AGENT", "PLAYER", "alice"),
            ("PLAYER", "AGENT", "agt-aaaaaaaaaa"),
            ("OWNER", "PLAYER", "ownerplayer"),
            ("OWNER", "AGENT", "agt-aaaaaaaaaa"),
        )
        for role, kind, identifier in cases:
            with self.subTest(role=role, kind=kind):
                with self.assertRaises(IntegrityError), self.connection.begin_nested():
                    self.identity(self.account(role), kind, identifier)

    def test_updates_cannot_reassign_identity_or_change_bound_account_role(self) -> None:
        player = self.account("PLAYER")
        agent = self.account("AGENT")
        self.identity(player, "PLAYER", "alice")
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                update(PrivateIdentity.__table__)
                .where(PrivateIdentity.account_id == player)
                .values(account_id=agent)
            )
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                update(Account.__table__).where(Account.id == player).values(role="AGENT")
            )
        self.assertEqual(
            self.connection.scalar(select(Account.role).where(Account.id == player)), "PLAYER"
        )

    def test_null_kind_still_requires_existing_account(self) -> None:
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.identity(uuid.uuid4(), None, None)


if __name__ == "__main__":
    unittest.main()
