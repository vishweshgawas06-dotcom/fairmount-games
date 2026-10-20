"""Wallet and ledger operations. All point movements go through here or the roulette services.

Authorization (who may adjust whom, agent budgets) is enforced in a later phase (P04/P07); the
functions here take an explicit ``actor_id`` so the audit trail is complete from day one.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from fairmount_api.core.errors import (
    AccountNotFound,
    IdempotencyConflict,
    InsufficientBalance,
    InvalidAdjustment,
)
from fairmount_api.db.models import Account, LedgerEntry, LedgerType, Role, Wallet
from fairmount_api.db.session import run_in_transaction

MAX_REASON_LENGTH = 500
MAX_KEY_LENGTH = 128


def lock_wallet(session: Session, account_id: int) -> Wallet:
    """Fetch a wallet row with ``FOR UPDATE`` (serialises all changes to one balance)."""
    wallet = session.execute(
        select(Wallet).where(Wallet.account_id == account_id).with_for_update()
    ).scalar_one_or_none()
    if wallet is None:
        raise AccountNotFound()
    return wallet


def create_account(
    factory: sessionmaker[Session],
    *,
    role: Role,
    name: str,
    mobile: str | None = None,
    parent_id: int | None = None,
) -> int:
    """Create an account with a zero-balance wallet (players start at zero points)."""

    def work(session: Session) -> int:
        account = Account(role=role, name=name, mobile=mobile, parent_id=parent_id)
        session.add(account)
        session.flush()
        session.add(Wallet(account_id=account.id, balance=0))
        return account.id

    return run_in_transaction(factory, work)


def get_balance(factory: sessionmaker[Session], account_id: int) -> int:
    with factory() as session:
        balance = session.scalar(select(Wallet.balance).where(Wallet.account_id == account_id))
    if balance is None:
        raise AccountNotFound()
    return balance


def admin_adjust(
    factory: sessionmaker[Session],
    *,
    actor_id: int,
    account_id: int,
    amount: int,
    reason: str,
    idempotency_key: str,
) -> int:
    """Credit (positive) or debit (negative) a wallet with a mandatory reason. Returns balance.

    Retrying with the same ``idempotency_key`` and identical arguments is a no-op that returns the
    current balance; the same key with different arguments raises :class:`IdempotencyConflict`.
    """
    if isinstance(amount, bool) or not isinstance(amount, int) or amount == 0:
        raise InvalidAdjustment()
    if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON_LENGTH:
        raise InvalidAdjustment()
    if not isinstance(idempotency_key, str) or not 0 < len(idempotency_key) <= MAX_KEY_LENGTH:
        raise InvalidAdjustment()
    ledger_key = f"admin:{idempotency_key}"

    def work(session: Session) -> int:
        wallet = lock_wallet(session, account_id)
        existing = session.execute(
            select(LedgerEntry).where(LedgerEntry.idempotency_key == ledger_key)
        ).scalar_one_or_none()
        if existing is not None:
            if (existing.account_id, existing.amount) != (account_id, amount):
                raise IdempotencyConflict()
            return wallet.balance
        if wallet.balance + amount < 0:
            raise InsufficientBalance()
        session.add(
            LedgerEntry(
                account_id=account_id,
                entry_type=LedgerType.ADMIN_ADJUST,
                amount=amount,
                actor_id=actor_id,
                reason=reason.strip(),
                idempotency_key=ledger_key,
            )
        )
        wallet.balance += amount
        wallet.updated_at = func.now()
        return wallet.balance

    return run_in_transaction(factory, work)


def ledger_mismatches(factory: sessionmaker[Session]) -> list[tuple[int, int, int]]:
    """Return ``(account_id, wallet_balance, ledger_sum)`` for every wallet that disagrees.

    An empty list means every balance equals the sum of its ledger entries. Intended for a
    scheduled reconciliation job and for tests.
    """
    with factory() as session:
        ledger_sum = (
            select(
                LedgerEntry.account_id.label("account_id"),
                func.sum(LedgerEntry.amount).label("total"),
            )
            .group_by(LedgerEntry.account_id)
            .subquery()
        )
        rows = session.execute(
            select(Wallet.account_id, Wallet.balance, func.coalesce(ledger_sum.c.total, 0))
            .outerjoin(ledger_sum, ledger_sum.c.account_id == Wallet.account_id)
            .where(Wallet.balance != func.coalesce(ledger_sum.c.total, 0))
            .order_by(Wallet.account_id)
        ).all()
    return [(int(a), int(b), int(c)) for a, b, c in rows]
