"""Bet acceptance, caps, partial acceptance, idempotency and rebet (real PostgreSQL)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from fairmount_api.core.errors import (
    BettingClosed,
    CapExceeded,
    IdempotencyConflict,
    InsufficientBalance,
    InvalidRequest,
    InvalidSelection,
    InvalidStake,
    RoundNotFound,
)
from fairmount_api.db.models import Bet, LedgerEntry, NumberExposure, SelectionExposure
from fairmount_api.roulette import rounds
from fairmount_api.roulette.betting import place_bet, rebet
from fairmount_api.wallet.service import get_balance, ledger_mismatches
from tests.conftest import AFTER_CUTOFF, BETTING_NOW, CUTOFF, T0, snapshot

pytestmark = pytest.mark.db


def bet(factory, rnd, player, key, amount, idem, now=BETTING_NOW):
    return place_bet(
        factory,
        now=now,
        account_id=player,
        round_id=rnd,
        selection_key=key,
        amount=amount,
        idempotency_key=idem,
    )


class TestBasicAcceptance:
    def test_accepts_bet_debits_wallet_and_writes_ledger(self, factory, open_round, make_player):
        p = make_player(1000)
        r = bet(factory, open_round, p, "straight:17", 100, "k1")
        assert (r.accepted, r.requested, r.returned_excess, r.balance_after) == (100, 100, 0, 900)
        assert get_balance(factory, p) == 900
        with factory() as s:
            row = s.execute(select(Bet)).scalar_one()
            assert (row.selection_key, row.bet_type, row.amount) == ("straight:17", "straight", 100)
            stake = s.execute(
                select(LedgerEntry).where(LedgerEntry.bet_id == row.id)
            ).scalar_one()
            assert (stake.amount, stake.entry_type.value) == (-100, "BET_STAKE")
        assert ledger_mismatches(factory) == []

    def test_selection_is_normalised_before_storing(self, factory, open_round, make_player):
        p = make_player(100)
        r = bet(factory, open_round, p, "Split:20-17", 10, "k1")
        assert r.selection_key == "split:17-20"

    def test_unknown_round(self, factory, make_player):
        p = make_player(100)
        with pytest.raises(RoundNotFound):
            bet(factory, 999, p, "red", 10, "k1")

    def test_unknown_account(self, factory, open_round):
        from fairmount_api.core.errors import AccountNotFound

        with pytest.raises(AccountNotFound):
            bet(factory, open_round, 424242, "red", 10, "k1")

    @pytest.mark.parametrize("stake", [0, 3, -5, 12, 5.0, "10", None, True])
    def test_invalid_stake_rejected(self, factory, open_round, make_player, stake):
        p = make_player(100)
        before = snapshot(factory, p)
        with pytest.raises(InvalidStake):
            bet(factory, open_round, p, "red", stake, "k1")
        assert snapshot(factory, p) == before

    @pytest.mark.parametrize("key", ["", "straight:99", "split:1-5", "banana", None])
    def test_invalid_selection_rejected(self, factory, open_round, make_player, key):
        p = make_player(100)
        before = snapshot(factory, p)
        with pytest.raises(InvalidSelection):
            bet(factory, open_round, p, key, 10, "k1")
        assert snapshot(factory, p) == before

    @pytest.mark.parametrize("idem", ["", None, "x" * 129, 5])
    def test_invalid_idempotency_key_rejected(self, factory, open_round, make_player, idem):
        p = make_player(100)
        with pytest.raises(InvalidRequest):
            bet(factory, open_round, p, "red", 10, idem)


class TestCutoff:
    def test_rejected_at_and_after_cutoff(self, factory, open_round, make_player):
        p = make_player(100)
        before = snapshot(factory, p)
        for t in (CUTOFF, AFTER_CUTOFF):
            with pytest.raises(BettingClosed):
                bet(factory, open_round, p, "red", 10, "k1", now=t)
        assert snapshot(factory, p) == before

    def test_accepted_one_microsecond_before_cutoff(self, factory, open_round, make_player):
        p = make_player(100)
        r = bet(factory, open_round, p, "red", 10, "k1", now=CUTOFF - timedelta(microseconds=1))
        assert r.accepted == 10

    def test_rejected_before_round_opens(self, factory, open_round, make_player):
        p = make_player(100)
        with pytest.raises(BettingClosed):
            bet(factory, open_round, p, "red", 10, "k1", now=T0 - timedelta(seconds=1))

    def test_rejected_once_round_is_closed_even_if_clock_is_early(
        self, factory, open_round, make_player
    ):
        p = make_player(100)
        rounds.close_round(factory, open_round, now=AFTER_CUTOFF, rng=lambda: 5)
        with pytest.raises(BettingClosed):
            bet(factory, open_round, p, "red", 10, "k1", now=BETTING_NOW)


class TestBalance:
    def test_insufficient_balance_rejects_entire_bet_with_no_side_effects(
        self, factory, open_round, make_player
    ):
        p = make_player(50)
        before = snapshot(factory, p)
        with pytest.raises(InsufficientBalance):
            bet(factory, open_round, p, "straight:1", 55, "k1")
        assert snapshot(factory, p) == before  # not even an exposure row survives

    def test_no_balance_limited_partial_stake(self, factory, open_round, make_player):
        p = make_player(45)
        with pytest.raises(InsufficientBalance):
            bet(factory, open_round, p, "red", 50, "k1")
        assert get_balance(factory, p) == 45

    def test_can_bet_entire_balance(self, factory, open_round, make_player):
        p = make_player(50)
        assert bet(factory, open_round, p, "red", 50, "k1").balance_after == 0

    def test_cap_limited_partial_requires_full_requested_stake_to_be_affordable(
        self, factory, open_round, make_player
    ):
        p = make_player(1800)
        bet(factory, open_round, p, "straight:17", 1500, "k1")  # balance 300
        before = snapshot(factory, p)
        # Request 1000 would be cap-limited to 500, but the wallet cannot cover the full 1000.
        with pytest.raises(InsufficientBalance):
            bet(factory, open_round, p, "straight:17", 1000, "k2")
        assert snapshot(factory, p) == before


class TestNumberExposureCap:
    def test_spec_example_partial_acceptance_returns_excess(
        self, factory, open_round, make_player
    ):
        p = make_player(5000)
        bet(factory, open_round, p, "straight:17", 1500, "k1")
        r = bet(factory, open_round, p, "straight:17", 1000, "k2")
        assert (r.requested, r.accepted, r.returned_excess) == (1000, 500, 500)
        assert get_balance(factory, p) == 5000 - 1500 - 500  # excess never debited
        with factory() as s:
            amount = s.scalar(select(NumberExposure.amount).where(NumberExposure.number == 17))
        assert amount == 2000

    def test_cap_fully_used_rejects_with_no_side_effects(self, factory, open_round, make_player):
        p = make_player(5000)
        bet(factory, open_round, p, "straight:17", 2000, "k1")
        before = snapshot(factory, p)
        with pytest.raises(CapExceeded):
            bet(factory, open_round, p, "straight:17", 5, "k2")
        assert snapshot(factory, p) == before

    def test_split_consumes_exposure_on_both_numbers(self, factory, open_round, make_player):
        p = make_player(5000)
        bet(factory, open_round, p, "split:17-20", 300, "k1")
        with factory() as s:
            rows = dict(s.execute(select(NumberExposure.number, NumberExposure.amount)).all())
        assert rows == {17: 300, 20: 300}

    def test_straight_and_split_share_the_number_cap(self, factory, open_round, make_player):
        p = make_player(5000)
        bet(factory, open_round, p, "straight:17", 1500, "k1")
        r = bet(factory, open_round, p, "split:17-20", 1000, "k2")
        assert r.accepted == 500  # limited by number 17 (500 left) not number 20 (2000 left)
        with factory() as s:
            rows = dict(s.execute(select(NumberExposure.number, NumberExposure.amount)).all())
        assert rows == {17: 2000, 20: 500}

    def test_split_limited_by_the_tighter_of_its_two_numbers(
        self, factory, open_round, make_player
    ):
        p = make_player(9000)
        bet(factory, open_round, p, "straight:17", 1900, "k1")  # 100 left on 17
        bet(factory, open_round, p, "straight:20", 1950, "k2")  # 50 left on 20
        r = bet(factory, open_round, p, "split:17-20", 500, "k3")
        assert r.accepted == 50

    def test_split_rejected_when_either_number_is_full(self, factory, open_round, make_player):
        p = make_player(9000)
        bet(factory, open_round, p, "straight:20", 2000, "k1")
        with pytest.raises(CapExceeded):
            bet(factory, open_round, p, "split:17-20", 50, "k2")

    def test_cap_is_per_player(self, factory, open_round, make_player):
        a, b = make_player(5000), make_player(5000)
        bet(factory, open_round, a, "straight:17", 2000, "k1")
        r = bet(factory, open_round, b, "straight:17", 2000, "k1")
        assert r.accepted == 2000  # another player's bets never affect acceptance

    def test_cap_is_per_round(self, factory, open_round, make_player):
        p = make_player(9000)
        bet(factory, open_round, p, "straight:17", 2000, "k1")
        rounds.close_round(factory, open_round, now=AFTER_CUTOFF, rng=lambda: 3)
        rounds.settle_round(factory, open_round, now=AFTER_CUTOFF)
        second = rounds.create_round(
            factory, opens_at=AFTER_CUTOFF, closes_at=AFTER_CUTOFF + timedelta(seconds=50)
        )
        r = bet(factory, second, p, "straight:17", 2000, "k2", now=AFTER_CUTOFF)
        assert r.accepted == 2000


class TestSelectionCaps:
    @pytest.mark.parametrize(
        "key",
        [
            "red",
            "black",
            "odd",
            "even",
            "low",
            "high",
            "dozen:2",
            "column:3",
            "street:4-5-6",
            "street:0-1-2",
            "corner:1-2-4-5",
            "six_line:1-2-3-4-5-6",
            "first_four",
        ],
    )
    def test_each_selection_type_is_capped_at_2000(self, factory, open_round, make_player, key):
        p = make_player(9000)
        bet(factory, open_round, p, key, 1500, "k1")
        r = bet(factory, open_round, p, key, 1000, "k2")
        assert r.accepted == 500
        with pytest.raises(CapExceeded):
            bet(factory, open_round, p, key, 5, "k3")

    def test_duplicate_bets_stay_separate_records_but_share_one_cap(
        self, factory, open_round, make_player
    ):
        p = make_player(9000)
        for i in range(4):
            bet(factory, open_round, p, "red", 500, f"k{i}")
        with factory() as s:
            assert len(s.execute(select(Bet)).scalars().all()) == 4
            assert s.scalar(select(SelectionExposure.amount)) == 2000
        with pytest.raises(CapExceeded):
            bet(factory, open_round, p, "red", 5, "k9")

    def test_different_selections_have_independent_caps(self, factory, open_round, make_player):
        p = make_player(9000)
        bet(factory, open_round, p, "red", 2000, "k1")
        assert bet(factory, open_round, p, "black", 2000, "k2").accepted == 2000
        assert bet(factory, open_round, p, "dozen:1", 2000, "k3").accepted == 2000

    def test_equivalent_spellings_hit_the_same_cap(self, factory, open_round, make_player):
        p = make_player(9000)
        bet(factory, open_round, p, "corner:1-2-4-5", 2000, "k1")
        with pytest.raises(CapExceeded):
            bet(factory, open_round, p, "corner:5-4-2-1", 5, "k2")


class TestIdempotency:
    def test_retry_with_same_key_does_not_debit_twice(self, factory, open_round, make_player):
        p = make_player(1000)
        first = bet(factory, open_round, p, "red", 100, "same")
        second = bet(factory, open_round, p, "red", 100, "same")
        assert (first.bet_id, first.accepted) == (second.bet_id, second.accepted)
        assert second.replayed and not first.replayed
        assert get_balance(factory, p) == 900
        with factory() as s:
            assert len(s.execute(select(Bet)).scalars().all()) == 1

    def test_replay_still_works_after_betting_closed(self, factory, open_round, make_player):
        p = make_player(1000)
        bet(factory, open_round, p, "red", 100, "same")
        rounds.close_round(factory, open_round, now=AFTER_CUTOFF, rng=lambda: 5)
        again = bet(factory, open_round, p, "red", 100, "same", now=AFTER_CUTOFF)
        assert again.replayed  # lost-response retry still learns the original outcome

    def test_same_key_different_payload_conflicts(self, factory, open_round, make_player):
        p = make_player(1000)
        bet(factory, open_round, p, "red", 100, "same")
        before = snapshot(factory, p)
        with pytest.raises(IdempotencyConflict):
            bet(factory, open_round, p, "black", 100, "same")
        with pytest.raises(IdempotencyConflict):
            bet(factory, open_round, p, "red", 50, "same")
        assert snapshot(factory, p) == before

    def test_keys_are_scoped_per_account(self, factory, open_round, make_player):
        a, b = make_player(1000), make_player(1000)
        bet(factory, open_round, a, "red", 100, "shared-key")
        assert not bet(factory, open_round, b, "red", 100, "shared-key").replayed

    def test_replayed_partial_acceptance_reports_original_split(
        self, factory, open_round, make_player
    ):
        p = make_player(5000)
        bet(factory, open_round, p, "straight:17", 1500, "k1")
        first = bet(factory, open_round, p, "straight:17", 1000, "k2")
        again = bet(factory, open_round, p, "straight:17", 1000, "k2")
        assert (again.accepted, again.returned_excess) == (first.accepted, first.returned_excess)
        assert get_balance(factory, p) == 5000 - 2000


class TestRebet:
    def _place_set(self, factory, rnd, p):
        bet(factory, rnd, p, "red", 100, "a")
        bet(factory, rnd, p, "straight:17", 50, "b")
        bet(factory, rnd, p, "split:17-20", 20, "c")

    def _next_round(self, factory):
        return rounds.create_round(
            factory, opens_at=AFTER_CUTOFF, closes_at=AFTER_CUTOFF + timedelta(seconds=50)
        )

    def test_repeats_previous_bet_set_exactly(self, factory, open_round, make_player):
        p = make_player(1000)
        self._place_set(factory, open_round, p)
        nxt = self._next_round(factory)
        out = rebet(factory, now=AFTER_CUTOFF, account_id=p, round_id=nxt, idempotency_key="rb1")
        assert [(b.selection_key, b.accepted) for b in out.bets] == [
            ("red", 100),
            ("straight:17", 50),
            ("split:17-20", 20),
        ]
        assert out.balance_after == 1000 - 170 - 170
        assert ledger_mismatches(factory) == []

    def test_all_or_nothing_when_balance_is_short(self, factory, open_round, make_player):
        p = make_player(400)
        self._place_set(factory, open_round, p)  # balance 230, previous total 170
        nxt = self._next_round(factory)
        bet(factory, nxt, p, "black", 100, "burn", now=AFTER_CUTOFF)  # balance 130 < 170
        before = snapshot(factory, p)
        with pytest.raises(InsufficientBalance):
            rebet(factory, now=AFTER_CUTOFF, account_id=p, round_id=nxt, idempotency_key="rb1")
        assert snapshot(factory, p) == before  # not even the first affordable bet was placed

    def test_all_or_nothing_when_any_item_hits_a_cap(self, factory, open_round, make_player):
        p = make_player(9000)
        self._place_set(factory, open_round, p)
        nxt = self._next_round(factory)
        bet(factory, nxt, p, "straight:17", 1990, "fill", now=AFTER_CUTOFF)  # 10 left on 17
        before = snapshot(factory, p)
        with pytest.raises(CapExceeded):  # rebet's 50 on 17 would need partial acceptance
            rebet(factory, now=AFTER_CUTOFF, account_id=p, round_id=nxt, idempotency_key="rb1")
        assert snapshot(factory, p) == before

    def test_rejected_after_cutoff(self, factory, open_round, make_player):
        p = make_player(1000)
        self._place_set(factory, open_round, p)
        nxt = self._next_round(factory)
        late = AFTER_CUTOFF + timedelta(seconds=51)
        with pytest.raises(BettingClosed):
            rebet(factory, now=late, account_id=p, round_id=nxt, idempotency_key="rb1")

    def test_never_copies_another_players_bets(self, factory, open_round, make_player):
        a, b = make_player(1000), make_player(1000)
        self._place_set(factory, open_round, a)
        nxt = self._next_round(factory)
        with pytest.raises(InvalidRequest):
            rebet(factory, now=AFTER_CUTOFF, account_id=b, round_id=nxt, idempotency_key="rb1")
        assert snapshot(factory, b)["bets"] == 0

    def test_nothing_to_rebet(self, factory, open_round, make_player):
        p = make_player(1000)
        with pytest.raises(InvalidRequest):
            rebet(factory, now=BETTING_NOW, account_id=p, round_id=open_round, idempotency_key="x")

    def test_retry_does_not_duplicate(self, factory, open_round, make_player):
        p = make_player(1000)
        self._place_set(factory, open_round, p)
        nxt = self._next_round(factory)
        one = rebet(factory, now=AFTER_CUTOFF, account_id=p, round_id=nxt, idempotency_key="rb1")
        two = rebet(factory, now=AFTER_CUTOFF, account_id=p, round_id=nxt, idempotency_key="rb1")
        assert two.replayed and [b.bet_id for b in two.bets] == [b.bet_id for b in one.bets]
        assert get_balance(factory, p) == 1000 - 170 - 170
