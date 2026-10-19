"""PostgreSQL trigger tests for owner-approved fixed Agent IDs."""

import os
import unittest

from fairmount_api.db.models import Account, PrivateIdentity
from sqlalchemy import create_engine, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class FixedAgentIDTests(unittest.TestCase):
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

    def create_agent_identity(self, *, assigned=True):
        account_id = self.connection.execute(
            insert(Account.__table__).values(role="AGENT").returning(Account.id)
        ).scalar_one()
        self.connection.execute(
            insert(PrivateIdentity.__table__).values(
                account_id=account_id,
                login_kind="AGENT" if assigned else None,
                login_identifier="agt-aaaaaaaaaa" if assigned else None,
            )
        )
        return account_id

    def test_initial_assignment_and_profile_updates_remain_possible(self) -> None:
        account = self.create_agent_identity(assigned=False)
        self.connection.execute(
            update(PrivateIdentity.__table__)
            .where(PrivateIdentity.account_id == account)
            .values(login_kind="AGENT", login_identifier="agt-aaaaaaaaaa")
        )
        self.connection.execute(
            update(PrivateIdentity.__table__)
            .where(PrivateIdentity.account_id == account)
            .values(display_name="Agent Example", login_identifier="agt-aaaaaaaaaa")
        )
        self.assertEqual(
            self.connection.scalar(
                select(PrivateIdentity.display_name).where(PrivateIdentity.account_id == account)
            ),
            "Agent Example",
        )

    def test_assigned_id_cannot_be_changed_cleared_moved_or_deleted(self) -> None:
        first = self.create_agent_identity()
        second = self.create_agent_identity(assigned=False)
        for changes in (
            {"login_identifier": "agt-bbbbbbbbbb"},
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
            "agt-aaaaaaaaaa",
        )
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                delete(PrivateIdentity.__table__).where(PrivateIdentity.account_id == first)
            )

    def test_unassigned_agent_identity_can_be_deleted(self) -> None:
        account = self.create_agent_identity(assigned=False)
        self.connection.execute(
            delete(PrivateIdentity.__table__).where(PrivateIdentity.account_id == account)
        )


if __name__ == "__main__":
    unittest.main()
