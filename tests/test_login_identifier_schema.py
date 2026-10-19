"""PostgreSQL constraints for canonical login identifiers; no registration API exists."""

import os
import unittest

from fairmount_api.db.models import Account, PrivateIdentity
from fairmount_api.identity.identifiers import canonical_agent_id, canonical_player_username
from sqlalchemy import create_engine, insert, select
from sqlalchemy.exc import IntegrityError

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class LoginIdentifierSchemaTests(unittest.TestCase):
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

    def identity(self, role: str, kind: str | None, identifier: str | None, mobile="9999999999"):
        account_id = self.account(role)
        return self.connection.execute(
            insert(PrivateIdentity.__table__)
            .values(
                account_id=account_id,
                login_kind=kind,
                login_identifier=identifier,
                mobile_number=mobile,
            )
            .returning(PrivateIdentity.account_id)
        ).scalar_one()

    def test_global_player_and_agent_uniqueness_and_shared_mobile(self) -> None:
        first = self.identity("PLAYER", "PLAYER", canonical_player_username("Alice"))
        self.identity("PLAYER", "PLAYER", canonical_player_username("Bob"))
        self.assertEqual(
            self.connection.scalar(
                select(PrivateIdentity.login_identifier).where(PrivateIdentity.account_id == first)
            ),
            "alice",
        )
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.identity("PLAYER", "PLAYER", canonical_player_username("ALICE"))
        agent = canonical_agent_id("AGT-AAAAAAAAAA")
        self.identity("AGENT", "AGENT", agent)
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.identity("AGENT", "AGENT", canonical_agent_id(agent.upper()))

    def test_database_rejects_invalid_noncanonical_and_reserved_identifiers(self) -> None:
        invalid = (
            ("PLAYER", "Admin"),
            ("PLAYER", "admin"),
            ("PLAYER", "agt-anything"),
            ("PLAYER", "aéa"),
            ("PLAYER", "ab"),
            ("PLAYER", "_bad"),
            ("AGENT", "AGT-AAAAAAAAAA"),
            ("AGENT", "agt-aaaaaaaaa0"),
            ("UNKNOWN", "alice"),
            (None, "alice"),
            ("PLAYER", None),
        )
        for kind, identifier in invalid:
            with self.subTest(kind=kind, identifier=identifier):
                with self.assertRaises(IntegrityError), self.connection.begin_nested():
                    self.identity("PLAYER", kind, identifier)

    def test_identity_without_login_remains_possible_before_activation(self) -> None:
        first = self.identity("PLAYER", None, None)
        self.identity("PLAYER", None, None)
        self.assertIsNone(
            self.connection.scalar(
                select(PrivateIdentity.login_kind).where(PrivateIdentity.account_id == first)
            )
        )


if __name__ == "__main__":
    unittest.main()
