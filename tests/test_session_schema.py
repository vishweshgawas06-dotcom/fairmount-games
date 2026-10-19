"""PostgreSQL session constraint tests; no session issuance API exists."""

import os
import secrets
import unittest

from fairmount_api.db.models import Account, AccountSession
from sqlalchemy import create_engine, func, insert, select, text, update
from sqlalchemy.exc import IntegrityError

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class SessionSchemaTests(unittest.TestCase):
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

    def account(self, role):
        return self.connection.execute(
            insert(Account.__table__).values(role=role).returning(Account.id)
        ).scalar_one()

    def session(self, account_id, role, **overrides):
        idle = "15 minutes" if role == "OWNER" else "30 minutes"
        absolute = {"OWNER": "8 hours", "AGENT": "12 hours", "PLAYER": "24 hours"}[role]
        values = {
            "account_id": account_id,
            "role_at_issue": role,
            "token_digest": secrets.token_hex(32),
            "issued_at": func.now(),
            "last_seen_at": func.now(),
            "idle_expires_at": func.now() + text(f"interval '{idle}'"),
            "absolute_expires_at": func.now() + text(f"interval '{absolute}'"),
            "mfa_verified_at": func.now() if role == "OWNER" else None,
            **overrides,
        }
        return self.connection.execute(
            insert(AccountSession.__table__).values(**values).returning(AccountSession.id)
        ).scalar_one()

    def test_valid_role_specific_expiries_and_mfa(self) -> None:
        for role in ("OWNER", "AGENT", "PLAYER"):
            with self.subTest(role=role):
                account = self.account(role)
                session_id = self.session(account, role)
                self.assertEqual(
                    self.connection.scalar(
                        select(AccountSession.role_at_issue).where(AccountSession.id == session_id)
                    ),
                    role,
                )

    def test_one_active_session_and_unique_digest(self) -> None:
        player = self.account("PLAYER")
        first = self.session(player, "PLAYER")
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.session(player, "PLAYER")
        self.connection.execute(
            update(AccountSession.__table__)
            .where(AccountSession.id == first)
            .values(revoked_at=func.now())
        )
        self.session(player, "PLAYER")
        digest = self.connection.scalar(
            select(AccountSession.token_digest).where(AccountSession.id == first)
        )
        another = self.account("PLAYER")
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.session(another, "PLAYER", token_digest=digest)

    def test_database_rejects_invalid_shapes_and_role_mismatch(self) -> None:
        owner = self.account("OWNER")
        agent = self.account("AGENT")
        bad = (
            (owner, "OWNER", {"mfa_verified_at": None}),
            (owner, "OWNER", {"token_digest": "BAD"}),
            (owner, "OWNER", {"absolute_expires_at": func.now() + text("interval '9 hours'")}),
            (owner, "OWNER", {"idle_expires_at": func.now() + text("interval '16 minutes'")}),
            (agent, "AGENT", {"mfa_verified_at": func.now()}),
            (agent, "AGENT", {"last_seen_at": func.now() - text("interval '1 hour'")}),
            (agent, "AGENT", {"revoked_at": func.now() - text("interval '1 hour'")}),
            (agent, "PLAYER", {}),
        )
        for account_id, role, changes in bad:
            with self.subTest(role=role, changes=list(changes)):
                with self.assertRaises(IntegrityError), self.connection.begin_nested():
                    self.session(account_id, role, **changes)

    def test_role_update_rejected_when_bound_session_exists(self) -> None:
        player = self.account("PLAYER")
        self.session(player, "PLAYER")
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                update(Account.__table__).where(Account.id == player).values(role="AGENT")
            )


if __name__ == "__main__":
    unittest.main()
