"""PostgreSQL internal agent/player login transaction tests; no HTTP route."""

import os
import secrets
import unittest

from fairmount_api.db.models import (
    Account,
    AccountCredential,
    AccountSession,
    PrivateIdentity,
    SecurityEvent,
)
from fairmount_api.identity.credentials import hash_password
from fairmount_api.identity.member_login import MemberLoginUnavailable, issue_member_session
from fairmount_api.identity.session_validation import resolve_session
from sqlalchemy import create_engine, func, insert, select, text, update

from infrastructure.local_db_url import local_database_url

PASSWORD = "a long private member passphrase"


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class MemberLoginTests(unittest.TestCase):
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

    def member(self, role, *, activated=True):
        canonical = "agt-aaaaaaaaaa" if role == "AGENT" else "alice_01"
        account_id = self.connection.execute(
            insert(Account.__table__).values(role=role).returning(Account.id)
        ).scalar_one()
        self.connection.execute(
            insert(PrivateIdentity.__table__).values(
                account_id=account_id, login_kind=role, login_identifier=canonical
            )
        )
        if activated:
            self.connection.execute(
                insert(AccountCredential.__table__).values(
                    account_id=account_id,
                    initial_secret_issued_at=func.now() - text("interval '1 hour'"),
                    initial_secret_consumed_at=func.now(),
                    password_hash=hash_password(PASSWORD),
                    password_changed_at=func.now(),
                )
            )
        else:
            self.connection.execute(
                insert(AccountCredential.__table__).values(
                    account_id=account_id,
                    initial_secret_digest=secrets.token_hex(32),
                    initial_secret_expires_at=func.now() + text("interval '24 hours'"),
                )
            )
        return account_id

    def test_fixed_ids_and_role_specific_expiry_without_owner_mfa(self) -> None:
        self.member("AGENT")
        self.member("PLAYER")
        for role, label, absolute in (
            ("AGENT", "aGt-AaAaAaAaAa", "12 hours"),
            ("PLAYER", "ALICE_01", "24 hours"),
        ):
            with self.subTest(role=role):
                issued = issue_member_session(self.connection, role, label, PASSWORD)
                self.assertEqual(issued.role, role)
                self.assertNotIn(issued.token, repr(issued))
                resolved = resolve_session(self.connection, issued.token)
                self.assertEqual((resolved.role, resolved.account_id), (role, issued.account_id))
                row = self.connection.execute(
                    select(
                        AccountSession.issued_at,
                        AccountSession.absolute_expires_at,
                        AccountSession.idle_expires_at,
                        AccountSession.mfa_verified_at,
                    ).where(AccountSession.id == issued.session_id)
                ).one()
                self.assertEqual(
                    row.absolute_expires_at - row.issued_at,
                    self.connection.scalar(select(text(f"interval '{absolute}'"))),
                )
                self.assertIsNone(row.mfa_verified_at)
                self.assertLessEqual(row.idle_expires_at, row.absolute_expires_at)
                self.assertNotEqual(
                    self.connection.scalar(
                        select(AccountSession.token_digest).where(
                            AccountSession.id == issued.session_id
                        )
                    ),
                    issued.token,
                )

    def test_wrong_kind_password_or_pending_credentials_do_not_issue(self) -> None:
        self.member("AGENT")
        self.member("PLAYER", activated=False)
        for role, label, password in (
            ("OWNER", "AGT-AAAAAAAAAA", PASSWORD),
            ("PLAYER", "AGT-AAAAAAAAAA", PASSWORD),
            ("AGENT", "owner", PASSWORD),
            ("AGENT", "AGT-AAAAAAAAAA", "not the private member passphrase"),
            ("PLAYER", "Alice_01", PASSWORD),
        ):
            with self.subTest(role=role, label=label):
                with self.assertRaises(MemberLoginUnavailable):
                    issue_member_session(self.connection, role, label, password)
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(AccountSession)), 0
        )

    def test_new_login_revokes_only_same_account_and_disable_blocks(self) -> None:
        agent = self.member("AGENT")
        self.member("PLAYER")
        player_session = issue_member_session(self.connection, "PLAYER", "alice_01", PASSWORD)
        first = issue_member_session(self.connection, "AGENT", "AGT-AAAAAAAAAA", PASSWORD)
        second = issue_member_session(self.connection, "AGENT", "AGT-AAAAAAAAAA", PASSWORD)
        self.assertIsNone(resolve_session(self.connection, first.token))
        self.assertEqual(resolve_session(self.connection, second.token).account_id, agent)
        self.assertIsNotNone(resolve_session(self.connection, player_session.token))
        self.connection.execute(
            update(Account.__table__).where(Account.id == agent).values(status="DISABLED")
        )
        self.assertIsNone(resolve_session(self.connection, second.token))
        self.assertIsNotNone(resolve_session(self.connection, player_session.token))
        with self.assertRaises(MemberLoginUnavailable):
            issue_member_session(self.connection, "AGENT", "AGT-AAAAAAAAAA", PASSWORD)

    def test_rollback_restores_previous_session_and_success_audit(self) -> None:
        self.member("PLAYER")
        first = issue_member_session(self.connection, "PLAYER", "Alice_01", PASSWORD)
        before = self.connection.scalar(select(func.count()).select_from(SecurityEvent))
        with self.assertRaises(RuntimeError), self.connection.begin_nested():
            issue_member_session(self.connection, "PLAYER", "Alice_01", PASSWORD)
            raise RuntimeError("Simulated transaction rollback")
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(SecurityEvent)), before
        )
        self.assertIsNotNone(resolve_session(self.connection, first.token))
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(AccountSession)), 1
        )


if __name__ == "__main__":
    unittest.main()
