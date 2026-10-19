"""PostgreSQL-only constraint tests for the first Alembic schema slice.

CI sets FAIRMOUNT_RUN_DB_TESTS=1 after migrating the isolated fairmount_test DB.
Local runs without that flag explicitly skip these tests rather than using SQLite.
"""

import os
import unittest
import uuid

from fairmount_api.db.models import Account, AgentAssignment, PrivateIdentity
from sqlalchemy import create_engine, func, insert, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class AccountSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(local_database_url(test=True))
        tables = set(inspect(cls.engine).get_table_names())
        required = {"accounts", "private_identities", "agent_assignments", "alembic_version"}
        if not required <= tables:
            cls.engine.dispose()
            raise AssertionError(f"Missing migrated account tables: {required - tables}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()

    def tearDown(self) -> None:
        self.transaction.rollback()
        self.connection.close()

    def account(self, role: str) -> uuid.UUID:
        return self.connection.execute(
            insert(Account.__table__).values(role=role).returning(Account.id)
        ).scalar_one()

    def test_single_owner_and_account_checks(self) -> None:
        self.account("OWNER")
        self.account("AGENT")
        self.account("PLAYER")
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.account("OWNER")
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.account("UNKNOWN")
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(insert(Account.__table__).values(role="PLAYER", status="BAD"))

    def test_identity_is_separate_and_requires_an_account(self) -> None:
        player = self.account("PLAYER")
        self.connection.execute(
            insert(PrivateIdentity.__table__).values(
                account_id=player, display_name="Example Player"
            )
        )
        self.assertEqual(
            self.connection.scalar(
                select(PrivateIdentity.display_name).where(PrivateIdentity.account_id == player)
            ),
            "Example Player",
        )
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                insert(PrivateIdentity.__table__).values(account_id=player)
            )
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                insert(PrivateIdentity.__table__).values(account_id=uuid.uuid4())
            )

    def test_owner_managed_player_and_single_current_assignment(self) -> None:
        owner = self.account("OWNER")
        agent_a = self.account("AGENT")
        agent_b = self.account("AGENT")
        player = self.account("PLAYER")
        owner_managed = self.account("PLAYER")
        self.assertIsNone(
            self.connection.scalar(
                select(AgentAssignment.id).where(
                    AgentAssignment.player_account_id == owner_managed
                )
            )
        )
        first = self.connection.execute(
            insert(AgentAssignment.__table__)
            .values(
                player_account_id=player,
                agent_account_id=agent_a,
                actor_account_id=owner,
                started_at=func.now() - text("interval '1 minute'"),
            )
            .returning(AgentAssignment.id)
        ).scalar_one()
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                insert(AgentAssignment.__table__).values(
                    player_account_id=player,
                    agent_account_id=agent_b,
                    actor_account_id=owner,
                )
            )
        self.connection.execute(
            update(AgentAssignment.__table__)
            .where(AgentAssignment.id == first)
            .values(ended_at=func.now())
        )
        self.connection.execute(
            insert(AgentAssignment.__table__).values(
                player_account_id=player,
                agent_account_id=agent_b,
                actor_account_id=owner,
            )
        )
        self.assertEqual(
            self.connection.scalar(
                select(AgentAssignment.agent_account_id).where(
                    AgentAssignment.player_account_id == player,
                    AgentAssignment.ended_at.is_(None),
                )
            ),
            agent_b,
        )

    def test_assignment_references_and_interval_checks(self) -> None:
        owner = self.account("OWNER")
        agent = self.account("AGENT")
        player = self.account("PLAYER")
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                insert(AgentAssignment.__table__).values(
                    player_account_id=agent,
                    agent_account_id=agent,
                    actor_account_id=owner,
                )
            )
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                insert(AgentAssignment.__table__).values(
                    player_account_id=player,
                    agent_account_id=uuid.uuid4(),
                    actor_account_id=owner,
                )
            )
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                insert(AgentAssignment.__table__).values(
                    player_account_id=player,
                    agent_account_id=agent,
                    actor_account_id=owner,
                    started_at=func.now(),
                    ended_at=func.now() - text("interval '1 minute'"),
                )
            )


if __name__ == "__main__":
    unittest.main()
