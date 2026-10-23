"""Real PostgreSQL POOL-01 admission, caps, idempotency and cutoff tests."""

import os
import secrets
import unittest

from fairmount_api.db.models import (
    Account,
    AccountSession,
    AccountWallet,
    GameReserve,
    PointOperation,
    RouletteBet,
    RouletteRound,
)
from fairmount_api.identity.session_validation import session_token_digest
from fairmount_api.point_accounting import issue_owner_points, transfer_owner_points
from fairmount_api.reserve_funding import fund_game_reserve
from fairmount_api.roulette.admission import BetReplayConflict, BetUnavailable, place_bet
from fairmount_api.roulette.round_clock import open_round
from sqlalchemy import create_engine, func, insert, select, text, update

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class BetAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(local_database_url(test=True))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.owner = self.account("OWNER")
        self.player = self.account("PLAYER")
        self.owner_token = self.session(self.owner, "OWNER")
        self.player_token = self.session(self.player, "PLAYER")
        self.round = open_round(self.connection)

    def tearDown(self) -> None:
        self.transaction.rollback()
        self.connection.close()

    def account(self, role):
        return self.connection.execute(
            insert(Account.__table__).values(role=role).returning(Account.id)
        ).scalar_one()

    def session(self, account, role):
        token = secrets.token_urlsafe(32)
        is_owner = role == "OWNER"
        self.connection.execute(
            insert(AccountSession.__table__).values(
                account_id=account,
                role_at_issue=role,
                token_digest=session_token_digest(token),
                issued_at=func.now() - text("interval '5 minutes'") if is_owner else func.now(),
                last_seen_at=func.now(),
                idle_expires_at=func.now()
                + text("interval '15 minutes'" if is_owner else "interval '30 minutes'"),
                absolute_expires_at=func.now()
                + text("interval '7 hours 55 minutes'" if is_owner else "interval '24 hours'"),
                mfa_verified_at=func.now() - text("interval '5 minutes'") if is_owner else None,
            )
        )
        return token

    def seed(self, *, issued=500, player_points=100, reserve=340, another_player=None):
        issue_owner_points(
            self.connection,
            self.owner_token,
            amount=issued,
            reason="approved issuance",
            idempotency_key="seed-issue",
        )
        transfer_owner_points(
            self.connection,
            self.owner_token,
            member_account_id=self.player,
            amount=player_points,
            to_member=True,
            reason="player allocation",
            idempotency_key="seed-player",
        )
        if another_player is not None:
            transfer_owner_points(
                self.connection,
                self.owner_token,
                member_account_id=another_player,
                amount=player_points,
                to_member=True,
                reason="another allocation",
                idempotency_key="seed-another",
            )
        if reserve:
            fund_game_reserve(
                self.connection,
                self.owner_token,
                amount=reserve,
                reason="reserve funding",
                idempotency_key="seed-reserve",
            )

    def bet(self, *, token=None, selection="straight:17", amount=10, key="bet"):
        return place_bet(
            self.connection,
            token or self.player_token,
            round_id=self.round,
            selection_key=selection,
            requested=amount,
            idempotency_key=key,
        )

    def wallet(self, account):
        return self.connection.scalar(
            select(AccountWallet.balance).where(AccountWallet.account_id == account)
        )

    def reserve(self):
        return self.connection.scalar(select(GameReserve.balance).where(GameReserve.id == 1))

    def test_funded_straight_up_and_replay_do_not_double_debit(self):
        self.seed()
        first = self.bet(selection="straight:17")
        self.assertEqual((first.accepted, first.unaccepted, first.replayed), (10, 0, False))
        replay = self.bet(selection="STRAIGHT:17")
        self.assertEqual(first.bet_id, replay.bet_id)
        self.assertTrue(replay.replayed)
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual((self.wallet(self.player), self.reserve()), (90, 350))
        self.assertEqual(self.connection.scalar(select(func.count()).select_from(RouletteBet)), 1)

    def test_global_worst_payout_rejects_only_new_bet_atomically(self):
        self.seed()
        first = self.bet()
        with self.assertRaises(BetUnavailable), self.connection.begin_nested():
            self.bet(key="second")  # two bets on 17 would owe 700; reserve would be 360
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual((self.wallet(self.player), self.reserve()), (90, 350))
        self.assertEqual(self.connection.scalar(select(RouletteBet.id)), first.bet_id)
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(PointOperation)), 4
        )

    def test_initial_shortfall_rejects_without_consuming_stake(self):
        self.seed(reserve=339)
        with self.assertRaises(BetUnavailable), self.connection.begin_nested():
            self.bet()
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual((self.wallet(self.player), self.reserve()), (100, 339))
        self.assertEqual(self.connection.scalar(select(func.count()).select_from(RouletteBet)), 0)

    def test_refund_coverage_can_dominate_every_winning_number(self):
        self.seed(issued=500, player_points=200, reserve=0)
        self.bet(selection="red", amount=100)
        second = self.bet(selection="black", amount=100, key="black")
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual(second.accepted, 100)
        self.assertEqual((self.wallet(self.player), self.reserve()), (0, 200))
        self.assertEqual(self.connection.scalar(select(func.count()).select_from(RouletteBet)), 2)

    def test_distinct_players_and_numbers_share_one_global_outcome(self):
        other = self.account("PLAYER")
        token = self.session(other, "PLAYER")
        self.seed(issued=1000, another_player=other)
        self.bet(selection="straight:17")
        self.bet(token=token, selection="straight:36", key="other")
        with self.assertRaises(BetUnavailable), self.connection.begin_nested():
            self.bet(token=token, selection="straight:17", key="other-again")
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual(
            (self.wallet(self.player), self.wallet(other), self.reserve()), (90, 90, 360)
        )

    def test_cap_partial_acceptance_but_not_balance_limited_partial(self):
        self.seed(issued=80000, player_points=5000, reserve=70000)
        self.bet(selection="straight:17", amount=1995)
        partial = self.bet(selection="straight:17", amount=10, key="partial")
        self.assertEqual((partial.accepted, partial.unaccepted), (5, 5))
        self.assertEqual(self.wallet(self.player), 3000)
        with self.assertRaises(BetUnavailable), self.connection.begin_nested():
            self.bet(selection="straight:17", amount=5, key="cap-full")
        # Even when the cap would allow five, the FULL requested ten must fit.
        # A separate low-balance fixture exercises this ordering.
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual(self.reserve(), 72000)

    def test_full_requested_wallet_check_precedes_cap_partial(self):
        self.seed(issued=75000, player_points=2000, reserve=70000)
        self.bet(amount=1995)
        with self.assertRaises(BetUnavailable), self.connection.begin_nested():
            self.bet(amount=10, key="insufficient-full")
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual(self.wallet(self.player), 5)
        self.assertEqual(self.connection.scalar(select(func.count()).select_from(RouletteBet)), 1)

    def test_reused_key_changed_intent_and_closed_round_reject(self):
        self.seed()
        self.bet()
        with self.assertRaises(BetReplayConflict), self.connection.begin_nested():
            self.bet(selection="straight:18")
        with self.assertRaises(BetUnavailable), self.connection.begin_nested():
            self.bet(token=self.owner_token, key="owner-is-not-player")
        # A raw state change is only a test fixture; production void/refund must
        # settle all accepted bets and lock the reserve in one transaction.
        self.connection.execute(
            update(RouletteRound.__table__)
            .where(RouletteRound.id == self.round)
            .values(state="VOID_REFUNDED")
        )
        with self.assertRaises(BetUnavailable), self.connection.begin_nested():
            self.bet(key="after-close")
        self.assertTrue(self.bet().replayed)  # original confirmation remains replayable
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


if __name__ == "__main__":
    unittest.main()
