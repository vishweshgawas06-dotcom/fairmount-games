"""Round lifecycle: outcome persistence, settlement, void/refund, crash recovery."""

from __future__ import annotations

import inspect
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from fairmount_api.core.errors import BettingClosed, InvalidRequest, InvalidRoundState
from fairmount_api.db.models import Bet, LedgerEntry, LedgerType, Round, RoundState
from fairmount_api.roulette import rounds
from fairmount_api.roulette.betting import place_bet
from fairmount_api.wallet.service import get_balance, ledger_mismatches
from tests.conftest import AFTER_CUTOFF, BETTING_NOW, CUTOFF, snapshot

pytestmark = pytest.mark.db


def bet(factory, rnd, player, key, amount, idem):
    return place_bet(
        factory,
        now=BETTING_NOW,
        account_id=player,
        round_id=rnd,
        selection_key=key,
        amount=amount,
        idempotency_key=idem,
    )


def close(factory, rnd, number):
    return rounds.close_round(factory, rnd, now=AFTER_CUTOFF, rng=lambda: number)


def state_of(factory, rnd):
    with factory() as s:
        return s.scalar(select(Round.state).where(Round.id == rnd))


def ledger_types(factory, rnd):
    with factory() as s:
        return [
            (e.entry_type, e.amount)
            for e in s.execute(
                select(LedgerEntry).where(LedgerEntry.round_id == rnd).order_by(LedgerEntry.id)
            ).scalars()
        ]


class TestCloseRound:
    def test_persists_outcome_and_closes(self, factory, open_round):
        assert close(factory, open_round, 23) == 23
        with factory() as s:
            row = s.get(Round, open_round)
        assert (row.state, row.winning_number) == (RoundState.CLOSED, 23)

    def test_close_is_idempotent_and_never_regenerates_the_outcome(self, factory, open_round):
        assert close(factory, open_round, 23) == 23
        assert close(factory, open_round, 5) == 23  # a different rng must be ignored

    def test_cannot_close_before_cutoff(self, factory, open_round):
        with pytest.raises(InvalidRoundState):
            rounds.close_round(factory, open_round, now=BETTING_NOW, rng=lambda: 1)
        assert state_of(factory, open_round) is RoundState.OPEN

    @pytest.mark.parametrize("bad", [-1, 37, 1.5, "7", None, True])
    def test_invalid_random_source_output_is_never_persisted(self, factory, open_round, bad):
        with pytest.raises(RuntimeError):
            rounds.close_round(factory, open_round, now=AFTER_CUTOFF, rng=lambda: bad)
        with factory() as s:
            row = s.get(Round, open_round)
        assert (row.state, row.winning_number) == (RoundState.OPEN, None)

    def test_random_source_takes_no_inputs_and_covers_every_pocket(self):
        assert not inspect.signature(rounds.secure_random_pocket).parameters
        seen = {rounds.secure_random_pocket() for _ in range(4000)}
        assert seen == set(range(37))  # all 37 pockets reachable, none out of range


class TestSettlement:
    def test_straight_up_win_credits_total_payout_only(self, factory, open_round, make_player):
        p = make_player(1000)
        bet(factory, open_round, p, "straight:17", 10, "k1")
        close(factory, open_round, 17)
        summary = rounds.settle_round(factory, open_round, now=AFTER_CUTOFF)
        assert (summary.total_staked, summary.total_paid) == (10, 350)
        assert get_balance(factory, p) == 1000 - 10 + 350  # not 360: stake is not added again
        assert state_of(factory, open_round) is RoundState.SETTLED
        assert ledger_mismatches(factory) == []

    def test_losing_bet_pays_nothing_and_records_zero_payout(
        self, factory, open_round, make_player
    ):
        p = make_player(1000)
        bet(factory, open_round, p, "straight:17", 10, "k1")
        close(factory, open_round, 18)
        rounds.settle_round(factory, open_round, now=AFTER_CUTOFF)
        assert get_balance(factory, p) == 990
        with factory() as s:
            assert s.scalar(select(Bet.payout)) == 0
        assert [t for t, _ in ledger_types(factory, open_round)] == [LedgerType.BET_STAKE]

    def test_even_money_win_returns_only_the_stake(self, factory, open_round, make_player):
        p = make_player(1000)
        bet(factory, open_round, p, "red", 100, "k1")
        close(factory, open_round, 1)  # red
        rounds.settle_round(factory, open_round, now=AFTER_CUTOFF)
        assert get_balance(factory, p) == 1000  # approved convention: total payout == stake x 1

    def test_zero_beats_every_outside_bet_and_pays_straight_and_first_four(
        self, factory, open_round, make_player
    ):
        p = make_player(10000)
        for i, key in enumerate(["red", "black", "odd", "even", "low", "high", "dozen:1"]):
            bet(factory, open_round, p, key, 100, f"o{i}")
        bet(factory, open_round, p, "straight:0", 10, "s")
        bet(factory, open_round, p, "first_four", 10, "f")
        bet(factory, open_round, p, "split:0-2", 10, "z")
        close(factory, open_round, 0)
        summary = rounds.settle_round(factory, open_round, now=AFTER_CUTOFF)
        assert summary.total_paid == 10 * 35 + 10 * 8 + 10 * 17

    def test_overlapping_bets_settle_independently_with_one_aggregate_credit(
        self, factory, open_round, make_player
    ):
        p = make_player(5000)
        bet(factory, open_round, p, "straight:17", 10, "a")  # 350
        bet(factory, open_round, p, "split:17-20", 10, "b")  # 170
        bet(factory, open_round, p, "street:16-17-18", 10, "c")  # 110
        bet(factory, open_round, p, "black", 10, "d")  # 10 (17 is black)
        bet(factory, open_round, p, "straight:20", 10, "e")  # loses
        close(factory, open_round, 17)
        summary = rounds.settle_round(factory, open_round, now=AFTER_CUTOFF)
        assert summary.total_paid == 350 + 170 + 110 + 10
        payouts = [a for t, a in ledger_types(factory, open_round) if t is LedgerType.PAYOUT]
        assert payouts == [640]  # one aggregate credit per player
        assert ledger_mismatches(factory) == []

    def test_settling_twice_never_pays_twice(self, factory, open_round, make_player):
        p = make_player(1000)
        bet(factory, open_round, p, "straight:17", 10, "k1")
        close(factory, open_round, 17)
        first = rounds.settle_round(factory, open_round, now=AFTER_CUTOFF)
        second = rounds.settle_round(factory, open_round, now=AFTER_CUTOFF)
        assert not first.replayed and second.replayed
        assert second.total_paid == first.total_paid == 350
        assert get_balance(factory, p) == 1340

    def test_cannot_settle_an_open_round(self, factory, open_round, make_player):
        p = make_player(100)
        bet(factory, open_round, p, "red", 10, "k1")
        before = snapshot(factory, p)
        with pytest.raises(InvalidRoundState):
            rounds.settle_round(factory, open_round, now=AFTER_CUTOFF)
        assert snapshot(factory, p) == before

    def test_round_with_no_bets_settles_cleanly(self, factory, open_round):
        close(factory, open_round, 9)
        summary = rounds.settle_round(factory, open_round, now=AFTER_CUTOFF)
        assert (summary.total_staked, summary.total_paid) == (0, 0)

    def test_multiple_players_are_paid_correctly(self, factory, open_round, make_player):
        a, b, c = make_player(1000), make_player(1000), make_player(1000)
        bet(factory, open_round, a, "straight:7", 100, "k")
        bet(factory, open_round, b, "red", 200, "k")
        bet(factory, open_round, c, "black", 300, "k")
        close(factory, open_round, 7)  # red
        rounds.settle_round(factory, open_round, now=AFTER_CUTOFF)
        assert get_balance(factory, a) == 1000 - 100 + 3500
        assert get_balance(factory, b) == 1000
        assert get_balance(factory, c) == 700
        assert ledger_mismatches(factory) == []


class TestCrashDuringSettlement:
    def test_crash_mid_settlement_rolls_back_everything(self, factory, open_round, make_player):
        a, b = make_player(1000), make_player(1000)
        bet(factory, open_round, a, "straight:7", 100, "k")
        bet(factory, open_round, b, "straight:7", 100, "k")
        close(factory, open_round, 7)

        def crash_after_first_account(account_id):
            if account_id == a:
                raise RuntimeError("simulated process crash")

        with pytest.raises(RuntimeError):
            rounds.settle_round(
                factory, open_round, now=AFTER_CUTOFF, _after_account=crash_after_first_account
            )
        # Player a's credit was applied inside the transaction, then rolled back with it.
        assert get_balance(factory, a) == 900
        assert get_balance(factory, b) == 900
        assert state_of(factory, open_round) is RoundState.CLOSED
        assert all(t is LedgerType.BET_STAKE for t, _ in ledger_types(factory, open_round))
        with factory() as s:
            paid_bets = select(func.count()).select_from(Bet).where(Bet.payout.is_not(None))
            assert s.scalar(paid_bets) == 0

        # The retry succeeds and pays exactly once.
        rounds.settle_round(factory, open_round, now=AFTER_CUTOFF)
        assert get_balance(factory, a) == 900 + 3500
        assert get_balance(factory, b) == 900 + 3500
        assert ledger_mismatches(factory) == []


class TestVoidAndRefund:
    def test_void_refunds_every_stake_exactly_once(self, factory, open_round, make_player):
        a, b = make_player(1000), make_player(1000)
        bet(factory, open_round, a, "red", 100, "k1")
        bet(factory, open_round, a, "straight:3", 50, "k2")
        bet(factory, open_round, b, "black", 200, "k1")
        close(factory, open_round, 3)
        first = rounds.void_round(factory, open_round, reason="engine fault", now=AFTER_CUTOFF)
        again = rounds.void_round(factory, open_round, reason="engine fault", now=AFTER_CUTOFF)
        assert (first.voided, first.total_refunded) == (True, 350)
        assert (again.voided, again.total_refunded) == (False, 0)
        assert get_balance(factory, a) == 1000 and get_balance(factory, b) == 1000
        assert ledger_mismatches(factory) == []
        with factory() as s:
            row = s.get(Round, open_round)
        assert row.state is RoundState.VOID_REFUNDED
        assert row.winning_number == 3  # persisted outcome retained for audit, never replaced
        assert row.void_reason == "engine fault"

    def test_settled_round_is_never_refunded(self, factory, open_round, make_player):
        p = make_player(1000)
        bet(factory, open_round, p, "straight:17", 10, "k")
        close(factory, open_round, 17)
        rounds.settle_round(factory, open_round, now=AFTER_CUTOFF)
        result = rounds.void_round(factory, open_round, reason="late void", now=AFTER_CUTOFF)
        assert not result.voided and result.state is RoundState.SETTLED
        assert get_balance(factory, p) == 1340  # paid once, not refunded

    def test_voided_round_cannot_be_settled(self, factory, open_round, make_player):
        p = make_player(1000)
        bet(factory, open_round, p, "straight:17", 10, "k")
        close(factory, open_round, 17)
        rounds.void_round(factory, open_round, reason="fault", now=AFTER_CUTOFF)
        with pytest.raises(InvalidRoundState):
            rounds.settle_round(factory, open_round, now=AFTER_CUTOFF)
        assert get_balance(factory, p) == 1000

    def test_void_while_betting_is_open_blocks_further_bets(
        self, factory, open_round, make_player
    ):
        p = make_player(1000)
        bet(factory, open_round, p, "red", 100, "k1")
        rounds.void_round(factory, open_round, reason="fault", now=BETTING_NOW)
        assert get_balance(factory, p) == 1000
        with pytest.raises(BettingClosed):
            bet(factory, open_round, p, "red", 100, "k2")

    @pytest.mark.parametrize("reason", ["", "   ", None])
    def test_void_requires_a_reason(self, factory, open_round, reason):
        with pytest.raises(InvalidRequest):
            rounds.void_round(factory, open_round, reason=reason, now=AFTER_CUTOFF)


class TestRecovery:
    def test_noop_when_already_terminal(self, factory, open_round):
        close(factory, open_round, 4)
        rounds.settle_round(factory, open_round, now=AFTER_CUTOFF)
        assert rounds.recover_round(factory, open_round, now=AFTER_CUTOFF) == "noop"

    def test_settles_a_closed_round(self, factory, open_round, make_player):
        p = make_player(1000)
        bet(factory, open_round, p, "straight:4", 10, "k")
        close(factory, open_round, 4)
        assert rounds.recover_round(factory, open_round, now=AFTER_CUTOFF) == "settled"
        assert get_balance(factory, p) == 1340

    def test_closes_and_settles_an_open_round_past_its_cutoff(
        self, factory, open_round, make_player
    ):
        p = make_player(1000)
        bet(factory, open_round, p, "red", 10, "k")
        assert rounds.recover_round(factory, open_round, now=AFTER_CUTOFF) == "settled"
        assert state_of(factory, open_round) is RoundState.SETTLED

    def test_transient_settlement_failure_is_retried(self, factory, open_round, make_player):
        p = make_player(1000)
        bet(factory, open_round, p, "straight:4", 10, "k")
        close(factory, open_round, 4)
        calls = {"n": 0}

        def flaky(fac, rid, *, now):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("db blip")
            return rounds.settle_round(fac, rid, now=now)

        outcome = rounds.recover_round(factory, open_round, now=AFTER_CUTOFF, settle=flaky)
        assert outcome == "settled"
        assert calls["n"] == 2
        assert get_balance(factory, p) == 1340  # paid once

    def test_persistent_failure_voids_and_refunds(self, factory, open_round, make_player):
        a, b = make_player(1000), make_player(1000)
        bet(factory, open_round, a, "straight:4", 100, "k")
        bet(factory, open_round, b, "red", 50, "k")
        close(factory, open_round, 4)

        def always_fails(fac, rid, *, now):
            raise ConnectionError("db down")

        result = rounds.recover_round(
            factory, open_round, now=AFTER_CUTOFF, max_attempts=2, settle=always_fails
        )
        assert result == "voided"
        assert get_balance(factory, a) == 1000 and get_balance(factory, b) == 1000
        with factory() as s:
            row = s.get(Round, open_round)
        assert row.state is RoundState.VOID_REFUNDED and row.winning_number == 4
        assert "ConnectionError" in row.void_reason
        # recovering again must not refund a second time
        assert rounds.recover_round(factory, open_round, now=AFTER_CUTOFF) == "noop"
        assert get_balance(factory, a) == 1000
        assert ledger_mismatches(factory) == []

    def test_unknown_round(self, factory):
        from fairmount_api.core.errors import RoundNotFound

        with pytest.raises(RoundNotFound):
            rounds.recover_round(factory, 12345, now=CUTOFF + timedelta(seconds=1))
