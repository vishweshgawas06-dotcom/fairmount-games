"""Round lifecycle: create, close (persist outcome once), settle, void/refund, recover.

Every transition is one transaction that takes the round row ``FOR UPDATE`` first. A round ends
in exactly one terminal state (SETTLED or VOID_REFUNDED); database triggers and unique ledger
keys make double payment or a payment-plus-refund impossible even if this code had a bug.
"""

from __future__ import annotations

import logging
import secrets
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from fairmount_api.core.errors import InvalidRequest, InvalidRoundState, RoundNotFound
from fairmount_api.db.models import Bet, LedgerEntry, LedgerType, Round, RoundState
from fairmount_api.db.session import run_in_transaction
from fairmount_api.roulette.catalogue import parse_selection_key
from fairmount_api.roulette.payout import total_payout
from fairmount_api.wallet.service import lock_wallet

logger = logging.getLogger(__name__)


def secure_random_pocket() -> int:
    """Cryptographically secure pocket 0-36, independent of bets, balances and players."""
    return secrets.randbelow(37)


@dataclass(frozen=True, slots=True)
class SettlementSummary:
    round_id: int
    winning_number: int
    total_staked: int
    total_paid: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class VoidSummary:
    round_id: int
    voided: bool  # False when nothing was done (already settled or already void)
    total_refunded: int
    state: RoundState


def _lock_round(session: Session, round_id: int) -> Round:
    rnd = session.execute(
        select(Round).where(Round.id == round_id).with_for_update()
    ).scalar_one_or_none()
    if rnd is None:
        raise RoundNotFound()
    return rnd


def create_round(
    factory: sessionmaker[Session], *, opens_at: datetime, closes_at: datetime
) -> int:
    def work(session: Session) -> int:
        rnd = Round(state=RoundState.OPEN, opens_at=opens_at, closes_at=closes_at)
        session.add(rnd)
        session.flush()
        return rnd.id

    return run_in_transaction(factory, work)


def close_round(
    factory: sessionmaker[Session],
    round_id: int,
    *,
    now: datetime,
    rng: Callable[[], int] = secure_random_pocket,
) -> int:
    """Freeze betting and persist the single outcome. Idempotent. Returns the winning number."""

    def work(session: Session) -> int:
        rnd = _lock_round(session, round_id)
        if rnd.state in (RoundState.CLOSED, RoundState.SETTLED):
            assert rnd.winning_number is not None
            return rnd.winning_number
        if rnd.state is RoundState.VOID_REFUNDED:
            raise InvalidRoundState()
        if now < rnd.closes_at:
            raise InvalidRoundState("The round cannot be closed before its cutoff time.")
        if rnd.winning_number is None:
            number = rng()
            if isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= 36:
                raise RuntimeError("random source returned an invalid pocket")
            rnd.winning_number = number
        rnd.state = RoundState.CLOSED
        return rnd.winning_number

    return run_in_transaction(factory, work)


def settle_round(
    factory: sessionmaker[Session],
    round_id: int,
    *,
    now: datetime,
    _after_account: Callable[[int], None] | None = None,
) -> SettlementSummary:
    """Pay every winning bet in one atomic, idempotent transaction.

    ``_after_account`` is a fault-injection hook for tests (called after each wallet credit).
    """

    def work(session: Session) -> SettlementSummary:
        rnd = _lock_round(session, round_id)
        bets = session.execute(
            select(Bet).where(Bet.round_id == round_id).order_by(Bet.id)
        ).scalars().all()
        staked = sum(b.amount for b in bets)

        if rnd.state is RoundState.SETTLED:
            paid = sum(b.payout or 0 for b in bets)
            return SettlementSummary(round_id, rnd.winning_number or 0, staked, paid, True)
        if rnd.state is not RoundState.CLOSED or rnd.winning_number is None:
            raise InvalidRoundState("Only a closed round with a persisted outcome can settle.")

        winning = rnd.winning_number
        by_account: dict[int, list[Bet]] = defaultdict(list)
        for bet in bets:
            by_account[bet.account_id].append(bet)

        total_paid = 0
        for account_id in sorted(by_account):
            wallet = lock_wallet(session, account_id)
            account_total = 0
            for bet in by_account[account_id]:
                payout = total_payout(bet.amount, parse_selection_key(bet.selection_key), winning)
                bet.payout = payout
                account_total += payout
            if account_total > 0:
                session.add(
                    LedgerEntry(
                        account_id=account_id,
                        entry_type=LedgerType.PAYOUT,
                        amount=account_total,
                        round_id=round_id,
                        idempotency_key=f"payout:{round_id}:{account_id}",
                    )
                )
                wallet.balance += account_total
                wallet.updated_at = func.now()
            total_paid += account_total
            if _after_account is not None:
                _after_account(account_id)

        rnd.state = RoundState.SETTLED
        rnd.settled_at = now
        return SettlementSummary(round_id, winning, staked, total_paid)

    return run_in_transaction(factory, work)


def void_round(
    factory: sessionmaker[Session], round_id: int, *, reason: str, now: datetime
) -> VoidSummary:
    """Void a round that cannot settle and refund every accepted stake exactly once."""
    if not isinstance(reason, str) or not reason.strip():
        raise InvalidRequest("A reason is required to void a round.")

    def work(session: Session) -> VoidSummary:
        rnd = _lock_round(session, round_id)
        if rnd.state in (RoundState.SETTLED, RoundState.VOID_REFUNDED):
            return VoidSummary(round_id, False, 0, rnd.state)  # terminal: never refund twice

        stakes: dict[int, int] = defaultdict(int)
        for bet in session.execute(select(Bet).where(Bet.round_id == round_id)).scalars():
            stakes[bet.account_id] += bet.amount
        total = 0
        for account_id in sorted(stakes):
            wallet = lock_wallet(session, account_id)
            session.add(
                LedgerEntry(
                    account_id=account_id,
                    entry_type=LedgerType.REFUND,
                    amount=stakes[account_id],
                    round_id=round_id,
                    reason=reason.strip()[:500],
                    idempotency_key=f"refund:{round_id}:{account_id}",
                )
            )
            wallet.balance += stakes[account_id]
            wallet.updated_at = func.now()
            total += stakes[account_id]
        rnd.state = RoundState.VOID_REFUNDED
        rnd.void_reason = reason.strip()[:500]
        rnd.settled_at = now
        logger.warning("round %s voided (%s); refunded %s points", round_id, reason, total)
        return VoidSummary(round_id, True, total, RoundState.VOID_REFUNDED)

    return run_in_transaction(factory, work)


def recover_round(
    factory: sessionmaker[Session],
    round_id: int,
    *,
    now: datetime,
    max_attempts: int = 3,
    settle: Callable[..., SettlementSummary] = settle_round,
) -> str:
    """Drive a stuck round to a terminal state. Safe to call repeatedly and concurrently.

    Returns ``'noop'`` (already terminal), ``'settled'`` or ``'voided'``. If settlement cannot
    commit after ``max_attempts``, the round is voided and all stakes refunded (owner-approved
    rule); a persisted outcome is retained for audit and never regenerated.
    """
    with factory() as session:
        state = session.scalar(select(Round.state).where(Round.id == round_id))
    if state is None:
        raise RoundNotFound()
    if state in (RoundState.SETTLED, RoundState.VOID_REFUNDED):
        return "noop"

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            if state is RoundState.OPEN:
                close_round(factory, round_id, now=now)
                state = RoundState.CLOSED
            settle(factory, round_id, now=now)
            return "settled"
        except Exception as exc:  # any failure to commit triggers the owner-approved void rule
            last_error = exc
            logger.error(
                "settlement attempt %d/%d failed for round %s",
                attempt,
                max_attempts,
                round_id,
                exc_info=True,
            )
    reason = f"settlement failed after {max_attempts} attempts: {type(last_error).__name__}"
    summary = void_round(factory, round_id, reason=reason, now=now)
    return "voided" if summary.voided else "noop"
