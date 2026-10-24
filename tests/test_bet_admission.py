"""Real PostgreSQL POOL-01 admission, caps, idempotency and cutoff tests."""

import os
import secrets
import unittest
from datetime import timedelta

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
from fairmount_api.point_accounting import (
    PointActionConflict,
    PointActionUnavailable,
    issue_owner_points,
    transfer_owner_points,
)
from fairmount_api.point_reconciliation import reconcile_points
from fairmount_api.reserve_funding import fund_game_reserve, withdraw_surplus_reserve
from fairmount_api.roulette.admission import BetReplayConflict, BetUnavailable, place_bet
from fairmount_api.roulette.rebet import RebetConflict, RebetUnavailable, repeat_previous_bets
from fairmount_api.roulette.recovery import advance_one_due_round, open_next_due_round
from fairmount_api.roulette.round_clock import close_round, open_round
from fairmount_api.roulette.settlement import (
    SettlementUnavailable,
    refund_void_round,
    settle_round,
)
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
        self.connection = self.engine.connect().execution_options(isolation_level="REPEATABLE READ")
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

    def advance_round_clock_fixture(self, seconds=61):
        # Privileged test-only time warp; production cannot bypass round guard.
        # Re-enable the guard before exercising the public service boundary.
        opened = self.connection.scalar(select(func.clock_timestamp())) - timedelta(seconds=seconds)
        self.connection.execute(text("ALTER TABLE roulette_rounds DISABLE TRIGGER tr_round_guard"))
        self.connection.execute(
            update(RouletteRound.__table__)
            .where(RouletteRound.id == self.round)
            .values(
                opens_at=opened,
                closes_at=opened + timedelta(seconds=50),
                reveal_at=opened + timedelta(seconds=60),
            )
        )
        self.connection.execute(text("ALTER TABLE roulette_rounds ENABLE TRIGGER tr_round_guard"))

    def prepare_rebet_source(
        self, *, issued=1000, player_points=100, reserve=340, source_bets=("straight:17",)
    ):
        self.seed(issued=issued, player_points=player_points, reserve=reserve)
        for n, selection in enumerate(source_bets):
            self.bet(selection=selection, amount=10, key=f"original-{n}")
        source = self.round
        self.advance_round_clock_fixture()
        close_round(self.connection, source, _test_rng=lambda: 0)
        settle_round(self.connection, source)
        self.round = open_round(self.connection)
        return source

    def test_rebet_previous_player_set_is_full_and_replayable_after_cutoff(self):
        source = self.prepare_rebet_source(source_bets=("straight:17", "straight:36"))
        first = repeat_previous_bets(
            self.connection,
            self.player_token,
            target_round_id=self.round,
            idempotency_key="repeat-original",
        )
        self.assertEqual((first.source_round_id, first.target_round_id), (source, self.round))
        self.assertEqual(len(first.bets), 2)
        self.assertFalse(first.replayed)
        self.assertTrue(all(bet.accepted == bet.requested == 10 for bet in first.bets))
        # Test-only time warp closes the target; a retry must replay without
        # creating another BET_STAKE or needing a still-open betting window.
        self.advance_round_clock_fixture()
        close_round(self.connection, self.round, _test_rng=lambda: 0)
        replay = repeat_previous_bets(
            self.connection,
            self.player_token,
            target_round_id=self.round,
            idempotency_key="repeat-original",
        )
        self.assertTrue(replay.replayed)
        self.assertEqual([bet.bet_id for bet in first.bets], [bet.bet_id for bet in replay.bets])
        next_round = open_round(self.connection)
        with self.assertRaises(RebetConflict):
            repeat_previous_bets(
                self.connection,
                self.player_token,
                target_round_id=next_round,
                idempotency_key="repeat-original",
            )
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual((self.wallet(self.player), self.reserve()), (60, 380))
        self.assertEqual(self.connection.scalar(select(func.count()).select_from(RouletteBet)), 4)
        self.assertTrue(reconcile_points(self.connection).balanced)

    def test_rebet_rejects_whole_set_on_full_wallet_or_cap_conflict(self):
        self.prepare_rebet_source()
        transfer_owner_points(
            self.connection,
            self.owner_token,
            member_account_id=self.player,
            amount=85,
            to_member=False,
            reason="test low wallet",
            idempotency_key="remove-for-rebet",
        )
        with self.assertRaises(RebetUnavailable):
            repeat_previous_bets(
                self.connection,
                self.player_token,
                target_round_id=self.round,
                idempotency_key="wallet-fail",
            )
        self.assertEqual(self.wallet(self.player), 5)
        self.assertEqual(self.connection.scalar(select(func.count()).select_from(RouletteBet)), 1)

    def test_rebet_rejects_cap_limited_partial_and_underfunded_bundle(self):
        self.prepare_rebet_source(
            issued=80000,
            player_points=5000,
            reserve=70000,
            source_bets=("straight:17", "straight:36"),
        )
        self.bet(selection="straight:36", amount=1995, key="target-cap")
        before = (self.wallet(self.player), self.reserve())
        with self.assertRaises(RebetUnavailable):
            repeat_previous_bets(
                self.connection,
                self.player_token,
                target_round_id=self.round,
                idempotency_key="cap-fail",
            )
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual((self.wallet(self.player), self.reserve()), before)
        self.assertEqual(self.connection.scalar(select(func.count()).select_from(RouletteBet)), 3)

        # Different fixture: a full-size repeated winner is legal under caps,
        # but cannot double the already accepted 350-point liability.
        # The separate test below checks this with a minimally funded reserve.

    def test_rebet_reserve_rejection_keeps_existing_target_bet(self):
        self.prepare_rebet_source()
        self.bet(selection="straight:17", amount=10, key="target-existing")
        before = (self.wallet(self.player), self.reserve())
        with self.assertRaises(RebetUnavailable):
            repeat_previous_bets(
                self.connection,
                self.player_token,
                target_round_id=self.round,
                idempotency_key="reserve-fail",
            )
        self.assertEqual((self.wallet(self.player), self.reserve()), before)
        self.assertEqual(self.connection.scalar(select(func.count()).select_from(RouletteBet)), 2)

    def test_late_due_worker_reuses_result_then_settles_without_auto_void(self):
        self.seed()
        self.bet()
        self.assertIsNone(advance_one_due_round(self.connection))
        self.assertIsNone(open_next_due_round(self.connection))
        self.advance_round_clock_fixture()
        first = advance_one_due_round(self.connection, _test_rng=lambda: 17)
        self.assertEqual((first.action, first.winning_number), ("RESULT_READY", 17))
        self.assertEqual(
            self.connection.scalar(
                select(RouletteRound.state).where(RouletteRound.id == self.round)
            ),
            "CLOSED",
        )
        with self.assertRaises(SettlementUnavailable):
            refund_void_round(
                self.connection, self.round, incident_reason="do not void known result"
            )
        second = advance_one_due_round(self.connection)
        self.assertEqual(
            (second.action, second.round_id, second.winning_number), ("SETTLED", self.round, 17)
        )
        self.assertIsNone(advance_one_due_round(self.connection))
        self.assertEqual((self.wallet(self.player), self.reserve()), (440, 0))
        new_round = open_next_due_round(self.connection)
        self.assertNotEqual(new_round, self.round)
        self.assertIsNone(open_next_due_round(self.connection))
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertTrue(reconcile_points(self.connection).balanced)

    def test_settlement_pays_disabled_winner_once_after_reveal(self):
        self.seed()
        self.bet()
        with self.assertRaises(SettlementUnavailable):
            settle_round(self.connection, self.round)
        self.advance_round_clock_fixture()
        self.assertEqual(close_round(self.connection, self.round, _test_rng=lambda: 17), 17)
        with self.assertRaises(SettlementUnavailable):
            refund_void_round(
                self.connection, self.round, incident_reason="result cannot be voided"
            )
        self.connection.execute(
            update(Account.__table__).where(Account.id == self.player).values(status="DISABLED")
        )
        first = settle_round(self.connection, self.round)
        second = settle_round(self.connection, self.round)
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual(
            (first.total_staked, first.total_credited, first.replayed), (10, 350, False)
        )
        self.assertEqual((second.total_credited, second.replayed), (350, True))
        self.assertEqual((self.wallet(self.player), self.reserve()), (440, 0))
        self.assertEqual(
            self.connection.scalar(
                select(func.count())
                .select_from(PointOperation)
                .where(PointOperation.kind == "PAYOUT", PointOperation.context_id == self.round)
            ),
            1,
        )
        self.assertTrue(reconcile_points(self.connection).balanced)
        with self.assertRaises(SettlementUnavailable):
            refund_void_round(self.connection, self.round, incident_reason="cannot cancel a payout")

    def test_losing_result_preserves_stakes_without_payout(self):
        self.seed()
        self.bet()
        self.advance_round_clock_fixture()
        close_round(self.connection, self.round, _test_rng=lambda: 36)
        result = settle_round(self.connection, self.round)
        self.assertEqual((result.total_staked, result.total_credited), (10, 0))
        self.assertEqual((self.wallet(self.player), self.reserve()), (90, 350))
        self.assertTrue(reconcile_points(self.connection).balanced)

    def test_owner_withdraws_only_surplus_while_winner_and_void_are_covered(self):
        self.seed()
        self.bet()
        with self.assertRaises(PointActionUnavailable):
            withdraw_surplus_reserve(
                self.connection,
                self.owner_token,
                amount=1,
                reason="cannot touch owed reserve",
                idempotency_key="shortfall",
            )
        fund_game_reserve(
            self.connection,
            self.owner_token,
            amount=20,
            reason="extra reserve",
            idempotency_key="extra-reserve",
        )
        result = withdraw_surplus_reserve(
            self.connection,
            self.owner_token,
            amount=20,
            reason="return surplus",
            idempotency_key="surplus",
        )
        replay = withdraw_surplus_reserve(
            self.connection,
            self.owner_token,
            amount=20,
            reason="return surplus",
            idempotency_key="surplus",
        )
        self.assertEqual(result.operation_id, replay.operation_id)
        self.assertTrue(replay.replayed)
        with self.assertRaises(PointActionConflict):
            withdraw_surplus_reserve(
                self.connection,
                self.owner_token,
                amount=15,
                reason="return surplus",
                idempotency_key="surplus",
            )
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual((self.wallet(self.player), self.reserve()), (90, 350))
        self.assertTrue(reconcile_points(self.connection).balanced)

    def test_withdrawal_rejects_wrong_actor_and_covers_full_void_refund(self):
        self.seed(issued=500, player_points=200, reserve=0)
        self.bet(selection="red", amount=100)
        self.bet(selection="black", amount=100, key="other-color")
        with self.assertRaises(PointActionUnavailable):
            withdraw_surplus_reserve(
                self.connection,
                self.player_token,
                amount=1,
                reason="unauthorized",
                idempotency_key="not-owner",
            )
        with self.assertRaises(PointActionUnavailable):
            withdraw_surplus_reserve(
                self.connection,
                self.owner_token,
                amount=1,
                reason="refund liability",
                idempotency_key="refund-shortfall",
            )
        fund_game_reserve(
            self.connection,
            self.owner_token,
            amount=25,
            reason="extra refund coverage",
            idempotency_key="refund-extra",
        )
        withdraw_surplus_reserve(
            self.connection,
            self.owner_token,
            amount=25,
            reason="return refund surplus",
            idempotency_key="refund-surplus",
        )
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual((self.wallet(self.player), self.reserve()), (0, 200))
        self.assertTrue(reconcile_points(self.connection).balanced)

    def test_two_unsettled_rounds_share_liability_and_release_only_finished_round(self):
        self.seed(issued=1000)
        self.bet(key="first")
        first_round = self.round
        self.advance_round_clock_fixture()
        close_round(self.connection, first_round, _test_rng=lambda: 17)
        self.round = open_round(self.connection)
        with self.assertRaises(BetUnavailable):
            self.bet(key="unfunded-second")
        fund_game_reserve(
            self.connection,
            self.owner_token,
            amount=340,
            reason="second-round protection",
            idempotency_key="second-fund",
        )
        self.bet(key="second")
        self.assertEqual(self.reserve(), 700)
        first = settle_round(self.connection, first_round)
        self.assertEqual((first.total_credited, self.reserve()), (350, 350))
        self.assertEqual(
            self.connection.scalar(
                select(RouletteRound.state).where(RouletteRound.id == self.round)
            ),
            "OPEN",
        )
        # Only the still-open round's full-void and payout exposure remains.
        voided = refund_void_round(
            self.connection, self.round, incident_reason="test-only explicit void primitive"
        )
        self.assertEqual((voided.total_credited, self.reserve()), (10, 340))
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertTrue(reconcile_points(self.connection).balanced)

    def test_void_refunds_every_accepted_stake_even_if_player_disabled(self):
        other = self.account("PLAYER")
        other_token = self.session(other, "PLAYER")
        self.seed(issued=1000, another_player=other)
        self.bet()
        self.bet(token=other_token, selection="straight:36", key="other")
        self.connection.execute(
            update(Account.__table__).where(Account.id == other).values(status="DISABLED")
        )
        result = refund_void_round(
            self.connection, self.round, incident_reason="test-only incident for recovery primitive"
        )
        retry = refund_void_round(self.connection, self.round, incident_reason="duplicate delivery")
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual((result.total_staked, result.total_credited), (20, 20))
        self.assertTrue(retry.replayed)
        self.assertEqual(
            (self.wallet(self.player), self.wallet(other), self.reserve()), (100, 100, 340)
        )
        self.assertTrue(reconcile_points(self.connection).balanced)
        with self.assertRaises(SettlementUnavailable):
            settle_round(self.connection, self.round)
        with self.assertRaises(BetUnavailable):
            self.bet(key="after-void")


if __name__ == "__main__":
    unittest.main()
