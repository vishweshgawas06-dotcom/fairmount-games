"""Property-based test: random bet sequences vs an independent oracle (real PostgreSQL)."""

from __future__ import annotations

from collections import defaultdict

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select, text

from fairmount_api.core.errors import FairMountError
from fairmount_api.db.models import NumberExposure, Role, SelectionExposure
from fairmount_api.db.session import make_session_factory
from fairmount_api.roulette import rounds
from fairmount_api.roulette.betting import place_bet
from fairmount_api.roulette.catalogue import CATALOGUE, parse_selection_key
from fairmount_api.roulette.payout import total_payout
from fairmount_api.wallet import service as wallet
from tests.conftest import AFTER_CUTOFF, BETTING_NOW, CUTOFF, T0, TABLES

pytestmark = pytest.mark.db

SELECTIONS = sorted(CATALOGUE)
bet_strategy = st.tuples(
    st.integers(min_value=0, max_value=2),  # player index
    st.sampled_from(SELECTIONS),
    st.integers(min_value=1, max_value=900).map(lambda n: n * 5),  # 5 .. 4500
)


@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(
    bets=st.lists(bet_strategy, min_size=1, max_size=25),
    winning=st.integers(min_value=0, max_value=36),
    void=st.booleans(),
)
def test_engine_matches_independent_oracle(engine, bets, winning, void):
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    factory = make_session_factory(engine)
    owner = wallet.create_account(factory, role=Role.OWNER, name="Owner")
    start = 3000
    players = []
    for i in range(3):
        pid = wallet.create_account(factory, role=Role.PLAYER, name=f"P{i}", parent_id=owner)
        wallet.admin_adjust(
            factory, actor_id=owner, account_id=pid, amount=start, reason="seed",
            idempotency_key=f"seed{i}",
        )
        players.append(pid)
    rid = rounds.create_round(factory, opens_at=T0, closes_at=CUTOFF)

    accepted = []  # (player, selection, accepted_amount) - oracle input from returned results
    for n, (pi, key, amount) in enumerate(bets):
        try:
            res = place_bet(
                factory, now=BETTING_NOW, account_id=players[pi], round_id=rid,
                selection_key=key, amount=amount, idempotency_key=f"b{n}",
            )
        except FairMountError:
            continue  # rejected requests must change nothing (checked by the oracle below)
        assert 5 <= res.accepted <= amount and res.accepted % 5 == 0
        assert res.returned_excess == amount - res.accepted
        accepted.append((players[pi], parse_selection_key(key), res.accepted))

    # Oracle 1: caps are never exceeded, computed independently from accepted bets.
    per_number = defaultdict(int)
    per_selection = defaultdict(int)
    for pl, sel, amt in accepted:
        if sel.uses_number_cap:
            for number in sel.numbers:
                per_number[(pl, number)] += amt
        else:
            per_selection[(pl, sel.key)] += amt
    assert all(v <= 2000 for v in per_number.values())
    assert all(v <= 2000 for v in per_selection.values())
    with factory() as s:
        db_numbers = {
            (r.account_id, r.number): r.amount for r in s.execute(select(NumberExposure)).scalars()
        }
        db_selections = {
            (r.account_id, r.selection_key): r.amount
            for r in s.execute(select(SelectionExposure)).scalars()
        }
    assert {k: v for k, v in db_numbers.items() if v} == dict(per_number)
    assert {k: v for k, v in db_selections.items() if v} == dict(per_selection)

    # Oracle 2: final balances equal start - stakes + independently computed payouts (or refund).
    rounds.close_round(factory, rid, now=AFTER_CUTOFF, rng=lambda: winning)
    if void:
        rounds.void_round(factory, rid, reason="property test", now=AFTER_CUTOFF)
    else:
        rounds.settle_round(factory, rid, now=AFTER_CUTOFF)
    for pl in players:
        stakes = sum(a for p, _, a in accepted if p == pl)
        if void:
            expected = start  # every accepted stake refunded, nothing else moves
        else:
            payouts = sum(total_payout(a, sel, winning) for p, sel, a in accepted if p == pl)
            expected = start - stakes + payouts
        assert wallet.get_balance(factory, pl) == expected
    # Oracle 3: the ledger always explains every balance.
    assert wallet.ledger_mismatches(factory) == []
