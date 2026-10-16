"""PostgreSQL integrity and append-only checks for minimal security events."""

import os
import unittest
import uuid

from fairmount_api.db.models import Account, SecurityEvent
from sqlalchemy import create_engine, delete, insert, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class SecurityEventSchemaTests(unittest.TestCase):
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

    def event(self, target, event_type, source, actor=None):
        return self.connection.execute(
            insert(SecurityEvent.__table__)
            .values(
                target_account_id=target,
                actor_account_id=actor,
                event_type=event_type,
                source=source,
            )
            .returning(SecurityEvent.id)
        ).scalar_one()

    def test_bootstrap_and_authenticated_events_have_minimal_fields(self) -> None:
        owner = self.account("OWNER")
        bootstrap = self.event(owner, "OWNER_BOOTSTRAP_ISSUED", "LOCAL_CLI")
        self.event(owner, "OWNER_BOOTSTRAP_REISSUED", "LOCAL_CLI")
        self.event(owner, "INITIAL_CREDENTIAL_CONSUMED", "SELF_SERVICE", actor=owner)
        self.assertEqual(
            self.connection.scalar(
                select(SecurityEvent.target_account_id).where(SecurityEvent.id == bootstrap)
            ),
            owner,
        )
        columns = {
            column["name"] for column in inspect(self.connection).get_columns("security_events")
        }
        self.assertEqual(
            columns,
            {"id", "event_type", "source", "actor_account_id", "target_account_id", "occurred_at"},
        )

    def test_invalid_events_and_missing_accounts_are_rejected(self) -> None:
        owner = self.account("OWNER")
        cases = (
            (owner, "BOGUS", "LOCAL_CLI", owner),
            (owner, "OWNER_BOOTSTRAP_ISSUED", "BOGUS", None),
            (owner, "PASSWORD_CHANGED", "SELF_SERVICE", None),
            (owner, "INITIAL_CREDENTIAL_ISSUED", "DASHBOARD", None),
            (uuid.uuid4(), "OWNER_BOOTSTRAP_ISSUED", "LOCAL_CLI", None),
            (owner, "PASSWORD_CHANGED", "SELF_SERVICE", uuid.uuid4()),
        )
        for target, kind, source, actor in cases:
            with self.subTest(kind=kind, source=source):
                with self.assertRaises(IntegrityError), self.connection.begin_nested():
                    self.event(target, kind, source, actor)

    def test_events_cannot_be_updated_deleted_or_truncated(self) -> None:
        owner = self.account("OWNER")
        event_id = self.event(owner, "OWNER_BOOTSTRAP_ISSUED", "LOCAL_CLI")
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                update(SecurityEvent.__table__)
                .where(SecurityEvent.id == event_id)
                .values(event_type="OWNER_BOOTSTRAP_REISSUED")
            )
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                delete(SecurityEvent.__table__).where(SecurityEvent.id == event_id)
            )
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(text("TRUNCATE security_events"))
        self.assertEqual(
            self.connection.scalar(
                select(SecurityEvent.event_type).where(SecurityEvent.id == event_id)
            ),
            "OWNER_BOOTSTRAP_ISSUED",
        )


if __name__ == "__main__":
    unittest.main()
