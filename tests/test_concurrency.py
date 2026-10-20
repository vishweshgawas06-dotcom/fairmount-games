"""Real multi-threaded contention against PostgreSQL: caps, idempotency, settle/void races."""

from __future__ import annotations

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from fairmount_api.core.errors import BettingClosed, CapExceeded
from fairmount_api.db.models import Bet, LedgerEntry, LedgerType, NumberExposure, Round, RoundState
from fairmount_api.roulette import rounds
from fairmount_api.roulette.betting import place_bet
from fairmount_api.wallet.service import get_balance, ledger_mismatches
from tests.conftest import AFTER_CUTOFF, BETTING_NOW

pytestmark = pytest.mark.db


def run_parallel(fns, workers=16):
    """Run callables simultaneously (barrier-aligned); return list of (ok, value_or_exc)."""
    barrier = threading.Barrier(len(fns))

    def wrap(fn):
        def inner():
            barrier.wait(timeout=30)
            try:
                return True, fn()
            except Exception as exc:  # collected and asserted on by the caller
                return False, exc

        return inner

    with ThreadPoolExecutor(max_workers=workers if workers >= len(fns) else len(fns)) as pool:
        futures = [pool.submit(wrap(fn)) for fn in fns]
        return [f.result(timeout=60) for f in futures]


def bet_call(factory, rnd, player, key, amount, idem):
    return lambda: place_bet(
        factory,
        now=BETTING_NOW,
        account_id=player,
        round_id=rnd,
        selection_key=key,
        amount=amount,
        idempotency_key=idem,
    )


class TestConcurrentBetting:
    def test_parallel_bets_can_never_exceed_the_number_cap(self, factory, open_round, make_player):
        p = make_player(100_000)
        calls = [bet_call(factory, open_round, p, "straight:17", 100, f"k{i}") for i in range(18)]
        results = run_parallel(calls)
        accepted = sum(v.accepted for ok, v in results if ok)
        rejected = [v for ok, v in results if not ok]
        assert accepted == 1800  # 18 x 100 requested; cap is 2000 so all fit
        assert not rejected

        calls = [bet_call(factory, open_round, p, "straight:17", 100, f"m{i}") for i in range(18)]
        results = run_parallel(calls)
        accepted_total = 1800 + sum(v.accepted for ok, v in results if ok)
        assert accepted_total == 2000  # exactly the cap, never a point more
        assert all(isinstance(v, CapExceeded) for ok, v in results if not ok)
        with factory() as s:
            assert s.scalar(select(NumberExposure.amount)) == 2000
            assert s.scalar(select(func.sum(Bet.amount))) == 2000
        assert get_balance(factory, p) == 100_000 - 2000
        assert ledger_mismatches(factory) == []

    def test_parallel_splits_and_straights_share_one_cap(self, factory, open_round, make_player):
        p = make_player(100_000)
        keys = ["straight:17", "split:17-20", "split:14-17", "straight:20", "split:16-17"] * 4
        calls = [bet_call(factory, open_round, p, k, 150, f"k{i}") for i, k in enumerate(keys)]
        run_parallel(calls)
        with factory() as s:
            exposure = dict(s.execute(select(NumberExposure.number, NumberExposure.amount)).all())
            staked_on_17 = s.scalar(
                select(func.sum(Bet.amount)).where(
                    Bet.selection_key.in_(
                        ["straight:17", "split:17-20", "split:14-17", "split:16-17"]
                    )
                )
            )
        assert max(exposure.values()) <= 2000
        assert exposure[17] == staked_on_17 <= 2000
        assert ledger_mismatches(factory) == []

    def test_same_idempotency_key_in_parallel_places_exactly_one_bet(
        self, factory, open_round, make_player
    ):
        p = make_player(1000)
        results = run_parallel([bet_call(factory, open_round, p, "red", 100, "dup")] * 12)
        assert all(ok for ok, _ in results)
        assert len({v.bet_id for _, v in results}) == 1
        assert Counter(v.replayed for _, v in results) == {False: 1, True: 11}
        assert get_balance(factory, p) == 900

    def test_many_players_betting_at_once_all_reconcile(self, factory, open_round, make_player):
        players = [make_player(1000) for _ in range(12)]
        calls = [
            bet_call(factory, open_round, pl, key, 100, f"k{i}")
            for pl in players
            for i, key in enumerate(["red", "straight:5", "split:5-8"])
        ]
        results = run_parallel(calls, workers=18)
        assert all(ok for ok, _ in results), [v for ok, v in results if not ok]
        assert all(get_balance(factory, pl) == 700 for pl in players)
        assert ledger_mismatches(factory) == []


class TestRacesWithClosing:
    def test_bets_racing_the_close_are_either_fully_in_or_cleanly_rejected(
        self, factory, open_round, make_player
    ):
        players = [make_player(1000) for _ in range(10)]
        calls = [bet_call(factory, open_round, pl, "red", 100, "k") for pl in players]
        calls.append(
            lambda: rounds.close_round(factory, open_round, now=AFTER_CUTOFF, rng=lambda: 1)
        )
        results = run_parallel(calls)
        bet_results = results[:-1]
        accepted = [v for ok, v in bet_results if ok]
        for ok, v in bet_results:
            assert ok or isinstance(v, BettingClosed)
        assert results[-1] == (True, 1)
        # Every accepted bet is frozen into the round; settling pays/loses them consistently.
        rounds.settle_round(factory, open_round, now=AFTER_CUTOFF)
        with factory() as s:
            assert s.scalar(select(func.count()).select_from(Bet)) == len(accepted)
        for pl in players:
            assert get_balance(factory, pl) in (900 + 100, 1000)  # red wins (1) -> stake back
        assert ledger_mismatches(factory) == []


class TestSettlementRaces:
    def _funded_closed_round(self, factory, open_round, make_player):
        a, b = make_player(1000), make_player(1000)
        place_bet(factory, now=BETTING_NOW, account_id=a, round_id=open_round,
                  selection_key="straight:7", amount=100, idempotency_key="k")
        place_bet(factory, now=BETTING_NOW, account_id=b, round_id=open_round,
                  selection_key="red", amount=100, idempotency_key="k")
        rounds.close_round(factory, open_round, now=AFTER_CUTOFF, rng=lambda: 7)
        return a, b

    def test_parallel_settlement_pays_exactly_once(self, factory, open_round, make_player):
        a, b = self._funded_closed_round(factory, open_round, make_player)
        results = run_parallel(
            [lambda: rounds.settle_round(factory, open_round, now=AFTER_CUTOFF)] * 10
        )
        assert all(ok for ok, _ in results)
        assert Counter(v.replayed for _, v in results) == {False: 1, True: 9}
        assert get_balance(factory, a) == 900 + 3500
        assert get_balance(factory, b) == 900 + 100
        with factory() as s:
            payouts = s.scalar(
                select(func.count()).select_from(LedgerEntry).where(
                    LedgerEntry.entry_type == LedgerType.PAYOUT
                )
            )
        assert payouts == 2
        assert ledger_mismatches(factory) == []

    def test_parallel_recovery_workers_pay_exactly_once(self, factory, open_round, make_player):
        a, _ = self._funded_closed_round(factory, open_round, make_player)
        results = run_parallel(
            [lambda: rounds.recover_round(factory, open_round, now=AFTER_CUTOFF)] * 8
        )
        assert all(ok for ok, _ in results)
        assert get_balance(factory, a) == 900 + 3500
        assert ledger_mismatches(factory) == []

    def test_settle_versus_void_race_ends_in_exactly_one_terminal_state(
        self, factory, open_round, make_player
    ):
        a, b = self._funded_closed_round(factory, open_round, make_player)
        calls = [lambda: rounds.settle_round(factory, open_round, now=AFTER_CUTOFF)] * 4
        calls += [
            lambda: rounds.void_round(factory, open_round, reason="race", now=AFTER_CUTOFF)
        ] * 4
        run_parallel(calls)
        with factory() as s:
            state = s.scalar(select(Round.state).where(Round.id == open_round))
            kinds = {
                e for (e,) in s.execute(
                    select(LedgerEntry.entry_type).where(LedgerEntry.round_id == open_round)
                )
            }
        assert state in (RoundState.SETTLED, RoundState.VOID_REFUNDED)
        if state is RoundState.SETTLED:
            assert LedgerType.REFUND not in kinds
            assert get_balance(factory, a) == 900 + 3500
        else:
            assert LedgerType.PAYOUT not in kinds
            assert get_balance(factory, a) == 1000 and get_balance(factory, b) == 1000
        assert ledger_mismatches(factory) == []
