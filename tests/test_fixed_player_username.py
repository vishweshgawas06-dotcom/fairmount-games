"""PostgreSQL trigger tests for fixed V1 player usernames."""

import os
import unittest

from fairmount_api.db.models import Account, PrivateIdentity
from sqlalchemy import create_engine, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class FixedPlayerUsernameTests(unittest.TestCase):
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

    def create_identity(self, *, role="PLAYER", kind="PLAYER", identifier="alice"):
        account_id = self.connection.execute(
            insert(Account.__table__).values(role=role).returning(Account.id)
        ).scalar_one()
        self.connection.execute(
            insert(PrivateIdentity.__table__).values(
                account_id=account_id, login_kind=kind, login_identifier=identifier
            )
        )
        return account_id

    def test_initial_assignment_and_profile_updates_remain_possible(self) -> None:
        account = self.create_identity(kind=None, identifier=None)
        self.connection.execute(
            update(PrivateIdentity.__table__)
            .where(PrivateIdentity.account_id == account)
            .values(login_kind="PLAYER", login_identifier="alice")
        )
        self.connection.execute(
            update(PrivateIdentity.__table__)
            .where(PrivateIdentity.account_id == account)
            .values(display_name="Alice Example", login_identifier="alice")
        )
        self.assertEqual(
            self.connection.scalar(
                select(PrivateIdentity.display_name).where(PrivateIdentity.account_id == account)
            ),
            "Alice Example",
        )

    def test_assigned_player_name_cannot_be_changed_cleared_or_moved(self) -> None:
        first = self.create_identity()
        second = self.create_identity(kind=None, identifier=None)
        for changes in (
            {"login_identifier": "alice2"},
            {"login_kind": None, "login_identifier": None},
            {"account_id": second},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(IntegrityError), self.connection.begin_nested():
                    self.connection.execute(
                        update(PrivateIdentity.__table__)
                        .where(PrivateIdentity.account_id == first)
                        .values(**changes)
                    )
        self.assertEqual(
            self.connection.scalar(
                select(PrivateIdentity.login_identifier).where(PrivateIdentity.account_id == first)
            ),
            "alice",
        )
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                delete(PrivateIdentity.__table__).where(PrivateIdentity.account_id == first)
            )

    def test_unassigned_and_agent_identities_are_not_player_username_updates(self) -> None:
        empty = self.create_identity(kind=None, identifier=None)
        self.connection.execute(
            delete(PrivateIdentity.__table__).where(PrivateIdentity.account_id == empty)
        )
        agent = self.create_identity(role="AGENT", kind="AGENT", identifier="agt-aaaaaaaaaa")
        self.connection.execute(
            update(PrivateIdentity.__table__)
            .where(PrivateIdentity.account_id == agent)
            .values(display_name="Agent Example")
        )


if __name__ == "__main__":
    unittest.main()
