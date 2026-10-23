"""Private owner issuance/transfer service; real PostgreSQL only, no HTTP route."""

import os
import secrets
import unittest
import uuid

from fairmount_api.db.models import (
    Account,
    AccountSession,
    AccountWallet,
    GameReserve,
    PointLedgerEntry,
    PointOperation,
)
from fairmount_api.identity.session_validation import session_token_digest
from fairmount_api.point_accounting import (
    PointActionConflict,
    PointActionUnavailable,
    issue_owner_points,
    transfer_owner_points,
)
from sqlalchemy import create_engine, func, insert, select, text, update

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class OwnerPointAccountingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(local_database_url(test=True))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.owner = self.connection.execute(
            insert(Account.__table__).values(role="OWNER").returning(Account.id)
        ).scalar_one()
        self.player = self.connection.execute(
            insert(Account.__table__).values(role="PLAYER").returning(Account.id)
        ).scalar_one()
        self.agent = self.connection.execute(
            insert(Account.__table__).values(role="AGENT").returning(Account.id)
        ).scalar_one()
        self.token = secrets.token_urlsafe(32)
        self.connection.execute(
            insert(AccountSession.__table__).values(
                account_id=self.owner,
                role_at_issue="OWNER",
                token_digest=session_token_digest(self.token),
                issued_at=func.now() - text("interval '5 minutes'"),
                last_seen_at=func.now(),
                idle_expires_at=func.now() + text("interval '15 minutes'"),
                absolute_expires_at=func.now() + text("interval '7 hours 55 minutes'"),
                mfa_verified_at=func.now() - text("interval '5 minutes'"),
            )
        )

    def tearDown(self) -> None:
        self.transaction.rollback()
        self.connection.close()

    def balance(self, account) -> int:
        return self.connection.scalar(
            select(AccountWallet.balance).where(AccountWallet.account_id == account)
        )

    def issue(self, amount=100, key="issue"):
        return issue_owner_points(
            self.connection, self.token, amount=amount, reason="owner pool", idempotency_key=key
        )

    def transfer(self, account=None, amount=30, to_member=True, key="transfer"):
        return transfer_owner_points(
            self.connection,
            self.token,
            member_account_id=account or self.player,
            amount=amount,
            to_member=to_member,
            reason="authorized allocation",
            idempotency_key=key,
        )

    def test_issue_then_transfer_and_return_conserve_supply(self) -> None:
        issue = self.issue(100)
        first = self.transfer(amount=30)
        second = self.transfer(account=self.agent, amount=40, key="agent")
        returned = self.transfer(amount=10, to_member=False, key="return")
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual(
            (self.balance(self.owner), self.balance(self.player), self.balance(self.agent)),
            (40, 20, 40),
        )
        self.assertEqual(self.connection.scalar(select(GameReserve.balance)), 0)
        self.assertEqual(
            len(
                {issue.operation_id, first.operation_id, second.operation_id, returned.operation_id}
            ),
            4,
        )
        self.assertEqual(self.connection.scalar(select(func.sum(PointLedgerEntry.delta))), 100)

    def test_identical_replay_does_not_reissue_or_retransfer(self) -> None:
        issue = self.issue()
        again = self.issue()
        self.assertEqual(again.operation_id, issue.operation_id)
        self.assertTrue(again.replayed)
        transfer = self.transfer()
        replay = self.transfer()
        self.assertEqual(replay.operation_id, transfer.operation_id)
        self.assertTrue(replay.replayed)
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual((self.balance(self.owner), self.balance(self.player)), (70, 30))
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(PointOperation)), 2
        )

    def test_changed_replay_and_unaffordable_full_transfer_leave_balances_untouched(self) -> None:
        self.issue(10)
        with self.assertRaises(PointActionConflict), self.connection.begin_nested():
            self.issue(11)
        with self.assertRaises(PointActionUnavailable), self.connection.begin_nested():
            self.transfer(amount=11)
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual((self.balance(self.owner), self.balance(self.player)), (10, 0))
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(PointOperation)), 1
        )

    def test_disabled_recipient_and_disabled_removal_are_blocked(self) -> None:
        self.issue(100)
        self.transfer()
        self.connection.execute(
            update(Account.__table__)
            .where(Account.id == self.player)
            .values(status="DISABLED", disabled_at=func.now())
        )
        with self.assertRaises(PointActionUnavailable), self.connection.begin_nested():
            self.transfer(amount=5, key="later")
        with self.assertRaises(PointActionUnavailable), self.connection.begin_nested():
            self.transfer(amount=5, key="remove", to_member=False)
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual((self.balance(self.owner), self.balance(self.player)), (70, 30))

    def test_invalid_owner_token_or_stale_mfa_and_invalid_input_fail_closed(self) -> None:
        with self.assertRaises(PointActionUnavailable), self.connection.begin_nested():
            issue_owner_points(
                self.connection,
                secrets.token_urlsafe(32),
                amount=10,
                reason="x",
                idempotency_key="bad",
            )
        for amount in (True, 0, -5, 2**63, 1.5):
            with self.subTest(amount=amount), self.assertRaises(PointActionUnavailable):
                self.issue(amount, key=str(amount))
        with self.assertRaises(PointActionUnavailable), self.connection.begin_nested():
            self.transfer(account=uuid.uuid4(), amount=10, key="missing-member")
        self.connection.execute(
            update(AccountSession.__table__)
            .where(AccountSession.token_digest == session_token_digest(self.token))
            .values(
                issued_at=func.now() - text("interval '11 minutes'"),
                mfa_verified_at=func.now() - text("interval '11 minutes'"),
                absolute_expires_at=func.now() + text("interval '7 hours 49 minutes'"),
            )
        )
        with self.assertRaises(PointActionUnavailable), self.connection.begin_nested():
            self.issue(10, key="stale")


if __name__ == "__main__":
    unittest.main()
