"""Immutable-ledger/wallet/reserve reconciliation with stable PostgreSQL snapshot."""

import os
import secrets
import unittest

from fairmount_api.db.models import Account, AccountSession, AccountWallet
from fairmount_api.identity.session_validation import session_token_digest
from fairmount_api.point_accounting import (
    PointActionUnavailable,
    issue_owner_points,
    transfer_owner_points,
)
from fairmount_api.point_reconciliation import BalanceMismatch, reconcile_points
from fairmount_api.reserve_funding import fund_game_reserve
from sqlalchemy import create_engine, func, insert, text, update
from sqlalchemy.exc import DBAPIError

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class PointReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(local_database_url(test=True))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.connection = self.engine.connect().execution_options(isolation_level="REPEATABLE READ")
        self.transaction = self.connection.begin()
        self.owner = self.connection.execute(
            insert(Account.__table__).values(role="OWNER").returning(Account.id)
        ).scalar_one()
        self.player = self.connection.execute(
            insert(Account.__table__).values(role="PLAYER").returning(Account.id)
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

    def seed(self) -> None:
        issue_owner_points(
            self.connection, self.token, amount=100, reason="issue", idempotency_key="issue"
        )
        transfer_owner_points(
            self.connection,
            self.token,
            member_account_id=self.player,
            amount=30,
            to_member=True,
            reason="player",
            idempotency_key="player",
        )
        fund_game_reserve(
            self.connection, self.token, amount=40, reason="reserve", idempotency_key="reserve"
        )
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    def test_all_wallets_reserve_and_global_supply_reconcile(self) -> None:
        self.seed()
        report = reconcile_points(self.connection)
        self.assertTrue(report.balanced)
        self.assertEqual(report.mismatches, ())
        self.assertEqual((report.current_supply, report.explicitly_issued), (100, 100))

    def test_rejected_transfer_cannot_change_report(self) -> None:
        self.seed()
        with self.assertRaises(PointActionUnavailable), self.connection.begin_nested():
            transfer_owner_points(
                self.connection,
                self.token,
                member_account_id=self.player,
                amount=31,
                to_member=False,
                reason="too much",
                idempotency_key="reject",
            )
        self.assertTrue(reconcile_points(self.connection).balanced)

    def test_detects_balance_drift_without_repairing_it(self) -> None:
        self.seed()
        with self.connection.begin_nested() as savepoint:
            # Simulate a privileged operator bypassing the migration's balance
            # trigger; DDL/privileged access is outside normal application rights.
            self.connection.execute(
                text("ALTER TABLE account_wallets DISABLE TRIGGER tr_guard_account_wallets")
            )
            self.connection.execute(
                update(AccountWallet.__table__)
                .where(AccountWallet.account_id == self.owner)
                .values(balance=31)
            )
            report = reconcile_points(self.connection)
            self.assertFalse(report.balanced)
            self.assertIn(BalanceMismatch(self.owner, 31, 30), report.mismatches)
            self.assertEqual((report.current_supply, report.explicitly_issued), (101, 100))
            savepoint.rollback()  # Restores data AND the table trigger.
        self.assertTrue(reconcile_points(self.connection).balanced)
        with self.assertRaises(DBAPIError), self.connection.begin_nested():
            self.connection.execute(
                update(AccountWallet.__table__)
                .where(AccountWallet.account_id == self.owner)
                .values(balance=31)
            )

    def test_read_committed_snapshot_is_not_accepted(self) -> None:
        with self.engine.begin() as other:
            with self.assertRaises(RuntimeError, msg="stable PostgreSQL snapshot"):
                reconcile_points(other)


if __name__ == "__main__":
    unittest.main()
