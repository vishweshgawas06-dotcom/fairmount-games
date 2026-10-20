"""Bet acceptance and rebet.

Lock order (everywhere in the engine, to make deadlocks impossible by construction):
    round row  ->  wallet row(s)  ->  exposure rows (ascending key order)

Placing a bet takes the round row ``FOR SHARE`` (many bets may proceed together) while closing,
settling and voiding take it ``FOR UPDATE`` (they wait for in-flight bets, and later bets see the
closed state). Every request is atomic: any failure rolls the whole transaction back, so a
rejected request has no wallet, ledger, bet or exposure side effects.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from fairmount_api.core.errors import (
    BettingClosed,
    CapExceeded,
    IdempotencyConflict,
    InsufficientBalance,
    InvalidRequest,
    RoundNotFound,
)
from fairmount_api.db.models import (
    Bet,
    IdempotencyRecord,
    LedgerEntry,
    LedgerType,
    NumberExposure,
    Round,
    RoundState,
    SelectionExposure,
    Wallet,
)
from fairmount_api.db.session import run_in_transaction
from fairmount_api.roulette.caps import (
    PER_NUMBER_CAP,
    PER_SELECTION_CAP,
    accepted_amount,
    validate_stake,
)
from fairmount_api.roulette.catalogue import Selection, parse_selection_key
from fairmount_api.wallet.service import lock_wallet

MAX_IDEMPOTENCY_KEY_LENGTH = 128


@dataclass(frozen=True, slots=True)
class BetResult:
    bet_id: int
    selection_key: str
    requested: int
    accepted: int
    returned_excess: int  # part of the request that was never debited (cap-limited)
    balance_after: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class RebetResult:
    bets: tuple[BetResult, ...]
    balance_after: int
    replayed: bool = False


def _storable(result: BetResult) -> dict[str, Any]:
    return {k: v for k, v in asdict(result).items() if k != "replayed"}


def _check_key(idempotency_key: object) -> str:
    if (
        not isinstance(idempotency_key, str)
        or not idempotency_key
        or len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH
    ):
        raise InvalidRequest("A valid idempotency key (1-128 characters) is required.")
    return idempotency_key


def _hash(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def _lock_open_round(session: Session, round_id: int) -> Round:
    rnd = session.execute(
        select(Round).where(Round.id == round_id).with_for_update(read=True)
    ).scalar_one_or_none()
    if rnd is None:
        raise RoundNotFound()
    return rnd


def _ensure_open(rnd: Round, now: datetime) -> None:
    if rnd.state is not RoundState.OPEN or now >= rnd.closes_at or now < rnd.opens_at:
        raise BettingClosed()


def _lock_exposures(
    session: Session, round_id: int, account_id: int, selection: Selection
) -> list[NumberExposure] | list[SelectionExposure]:
    """Create-if-missing then lock the relevant exposure rows in ascending key order."""
    if selection.uses_number_cap:
        numbers = sorted(selection.numbers)
        session.execute(
            pg_insert(NumberExposure)
            .values(
                [{"round_id": round_id, "account_id": account_id, "number": n} for n in numbers]
            )
            .on_conflict_do_nothing()
        )
        return list(
            session.execute(
                select(NumberExposure)
                .where(
                    NumberExposure.round_id == round_id,
                    NumberExposure.account_id == account_id,
                    NumberExposure.number.in_(numbers),
                )
                .order_by(NumberExposure.number)
                .with_for_update()
            ).scalars()
        )
    session.execute(
        pg_insert(SelectionExposure)
        .values(round_id=round_id, account_id=account_id, selection_key=selection.key)
        .on_conflict_do_nothing()
    )
    return list(
        session.execute(
            select(SelectionExposure)
            .where(
                SelectionExposure.round_id == round_id,
                SelectionExposure.account_id == account_id,
                SelectionExposure.selection_key == selection.key,
            )
            .with_for_update()
        ).scalars()
    )


def _accept(
    session: Session,
    *,
    wallet: Wallet,
    round_id: int,
    selection: Selection,
    amount: int,
    allow_partial: bool,
) -> tuple[Bet, int]:
    """Core acceptance step. Caller holds the round and wallet locks. Returns (bet, accepted)."""
    if wallet.balance < amount:
        raise InsufficientBalance()  # ordinary bets are rejected in full, never balance-limited

    exposures = _lock_exposures(session, round_id, wallet.account_id, selection)
    cap = PER_NUMBER_CAP if selection.uses_number_cap else PER_SELECTION_CAP
    accepted = accepted_amount(amount, [cap - e.amount for e in exposures])
    if accepted == 0 or (not allow_partial and accepted != amount):
        raise CapExceeded()

    bet = Bet(
        round_id=round_id,
        account_id=wallet.account_id,
        selection_key=selection.key,
        bet_type=selection.bet_type.value,
        requested_amount=amount,
        amount=accepted,
    )
    session.add(bet)
    session.flush()
    for exposure in exposures:
        exposure.amount += accepted
    wallet.balance -= accepted
    wallet.updated_at = func.now()
    session.add(
        LedgerEntry(
            account_id=wallet.account_id,
            entry_type=LedgerType.BET_STAKE,
            amount=-accepted,
            round_id=round_id,
            bet_id=bet.id,
            idempotency_key=f"stake:{bet.id}",
        )
    )
    return bet, accepted


def _result(bet: Bet, requested: int, balance_after: int) -> BetResult:
    return BetResult(
        bet_id=bet.id,
        selection_key=bet.selection_key,
        requested=requested,
        accepted=bet.amount,
        returned_excess=requested - bet.amount,
        balance_after=balance_after,
    )


def _stored(
    session: Session, account_id: int, key: str, request_hash: str
) -> dict[str, Any] | None:
    record = session.get(IdempotencyRecord, (account_id, key))
    if record is None:
        return None
    if record.request_hash != request_hash:
        raise IdempotencyConflict()
    return record.response


def place_bet(
    factory: sessionmaker[Session],
    *,
    now: datetime,
    account_id: int,
    round_id: int,
    selection_key: str,
    amount: int,
    idempotency_key: str,
) -> BetResult:
    """Accept one bet (possibly cap-limited) atomically and idempotently."""
    amount = validate_stake(amount)
    selection = parse_selection_key(selection_key)
    key = _check_key(idempotency_key)
    request_hash = _hash("bet", round_id, selection.key, amount)

    def work(session: Session) -> BetResult:
        rnd = _lock_open_round(session, round_id)
        wallet = lock_wallet(session, account_id)
        stored = _stored(session, account_id, key, request_hash)
        if stored is not None:
            return BetResult(**stored, replayed=True)
        _ensure_open(rnd, now)
        bet, _ = _accept(
            session,
            wallet=wallet,
            round_id=round_id,
            selection=selection,
            amount=amount,
            allow_partial=True,
        )
        result = _result(bet, amount, wallet.balance)
        session.add(
            IdempotencyRecord(
                account_id=account_id,
                key=key,
                request_hash=request_hash,
                response=_storable(result),
            )
        )
        return result

    return run_in_transaction(factory, work)


def rebet(
    factory: sessionmaker[Session],
    *,
    now: datetime,
    account_id: int,
    round_id: int,
    idempotency_key: str,
) -> RebetResult:
    """Repeat the caller's own most recent earlier bet set, all-or-nothing.

    Only the authenticated player's own bets are ever read. If any item cannot be accepted at its
    full amount (balance, caps, cutoff) nothing is placed.
    """
    key = _check_key(idempotency_key)
    request_hash = _hash("rebet", round_id)

    def work(session: Session) -> RebetResult:
        rnd = _lock_open_round(session, round_id)
        wallet = lock_wallet(session, account_id)
        stored = _stored(session, account_id, key, request_hash)
        if stored is not None:
            return RebetResult(
                bets=tuple(BetResult(**b, replayed=True) for b in stored["bets"]),
                balance_after=stored["balance_after"],
                replayed=True,
            )
        _ensure_open(rnd, now)
        previous_round = session.scalar(
            select(func.max(Bet.round_id)).where(
                Bet.account_id == account_id, Bet.round_id < round_id
            )
        )
        if previous_round is None:
            raise InvalidRequest("There are no previous bets to repeat.")
        previous = session.execute(
            select(Bet)
            .where(Bet.account_id == account_id, Bet.round_id == previous_round)
            .order_by(Bet.id)
        ).scalars().all()

        results: list[BetResult] = []
        for old in previous:
            bet, _ = _accept(
                session,
                wallet=wallet,
                round_id=round_id,
                selection=parse_selection_key(old.selection_key),
                amount=old.amount,
                allow_partial=False,
            )
            results.append(_result(bet, old.amount, wallet.balance))
        outcome = RebetResult(bets=tuple(results), balance_after=wallet.balance)
        session.add(
            IdempotencyRecord(
                account_id=account_id,
                key=key,
                request_hash=request_hash,
                response={
                    "bets": [_storable(r) for r in results],
                    "balance_after": wallet.balance,
                },
            )
        )
        return outcome

    return run_in_transaction(factory, work)
