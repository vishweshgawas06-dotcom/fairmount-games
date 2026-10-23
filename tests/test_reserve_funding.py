"""Funded-reserve owner transfer under PostgreSQL journal/step-up constraints."""

import os
import secrets
import unittest

from fairmount_api.db.models import (
    Account,
    AccountSession,
    AccountWallet,
    GameReserve,
    PointOperation,
)
from fairmount_api.identity.session_validation import session_token_digest
from fairmount_api.point_accounting import (
    PointActionConflict,
    PointActionUnavailable,
    issue_owner_points,
)
from fairmount_api.reserve_funding import fund_game_reserve
from sqlalchemy import create_engine, func, insert, select, text, update

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class ReserveFundingTests(unittest.TestCase):
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

    def seed(self, amount=100):
        return issue_owner_points(
            self.connection, self.token, amount=amount, reason="owner pool", idempotency_key="issue"
        )

    def fund(self, amount=60, key="fund", reason="separate reserve"):
        return fund_game_reserve(
            self.connection, self.token, amount=amount, reason=reason, idempotency_key=key
        )

    def balances(self):
        return (
            self.connection.scalar(
                select(AccountWallet.balance).where(AccountWallet.account_id == self.owner)
            ),
            self.connection.scalar(select(GameReserve.balance).where(GameReserve.id == 1)),
        )

    def test_owner_funds_existing_points_without_issuance_or_rng(self) -> None:
        self.seed()
        funding = self.fund()
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual(self.balances(), (40, 60))
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(PointOperation)), 2
        )
        self.assertEqual(
            self.connection.scalar(
                select(PointOperation.kind).where(PointOperation.id == funding.operation_id)
            ),
            "RESERVE_FUND",
        )

    def test_identical_replay_does_not_double_fund_but_changed_intent_conflicts(self) -> None:
        self.seed()
        original = self.fund()
        replay = self.fund()
        self.assertEqual(original.operation_id, replay.operation_id)
        self.assertTrue(replay.replayed)
        with self.assertRaises(PointActionConflict), self.connection.begin_nested():
            self.fund(reason="changed reason")
        with self.assertRaises(PointActionConflict), self.connection.begin_nested():
            self.fund(amount=61)
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual(self.balances(), (40, 60))

    def test_unaffordable_funding_rejects_whole_amount(self) -> None:
        self.seed(10)
        with self.assertRaises(PointActionUnavailable), self.connection.begin_nested():
            self.fund(11)
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual(self.balances(), (10, 0))
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(PointOperation)), 1
        )

    def test_invalid_token_stale_stepup_and_bad_amount_fail_closed(self) -> None:
        with self.assertRaises(PointActionUnavailable), self.connection.begin_nested():
            fund_game_reserve(
                self.connection,
                secrets.token_urlsafe(32),
                amount=1,
                reason="unauthorized",
                idempotency_key="invalid",
            )
        for amount in (True, 0, -1, 2**63, 1.5):
            with self.subTest(amount=amount), self.assertRaises(PointActionUnavailable):
                self.fund(amount, key=str(amount))
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
            self.fund(1, key="stale")
        self.assertEqual(self.balances(), (0, 0))


if __name__ == "__main__":
    unittest.main()
