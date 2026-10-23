"""Read-only reconciliation of materialized point balances and immutable journal.

Run under a stable PostgreSQL snapshot (or lock affected rows for an operational
check). A mismatch must alert/block writes; this module never repairs balances.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, func, select

from fairmount_api.db.models import AccountWallet, GameReserve, PointLedgerEntry, PointOperation


@dataclass(frozen=True)
class BalanceMismatch:
    wallet_account_id: uuid.UUID | None  # None means the separate reserve
    stored_balance: int
    journal_balance: int


@dataclass(frozen=True)
class ReconciliationReport:
    mismatches: tuple[BalanceMismatch, ...]
    current_supply: int
    explicitly_issued: int

    @property
    def balanced(self) -> bool:
        return not self.mismatches and self.current_supply == self.explicitly_issued


def reconcile_points(connection: Connection) -> ReconciliationReport:
    """Verify each wallet/reserve and the global issuance-conservation equation.

    The caller must provide a transactionally consistent snapshot; concurrent
    operations can otherwise change results between SELECT statements. This is
    not an authorization check or a substitute for DB operation constraints.
    """
    isolation = connection.exec_driver_sql("SHOW transaction_isolation").scalar_one()
    if isolation not in ("repeatable read", "serializable"):
        raise RuntimeError("Point reconciliation requires a stable PostgreSQL snapshot")
    sums = (
        select(
            PointLedgerEntry.wallet_account_id.label("wallet_account_id"),
            func.sum(PointLedgerEntry.delta).label("journal_balance"),
        )
        .where(PointLedgerEntry.wallet_account_id.is_not(None))
        .group_by(PointLedgerEntry.wallet_account_id)
        .subquery()
    )
    rows = connection.execute(
        select(
            AccountWallet.account_id,
            AccountWallet.balance,
            func.coalesce(sums.c.journal_balance, 0),
        )
        .outerjoin(sums, AccountWallet.account_id == sums.c.wallet_account_id)
        .order_by(AccountWallet.account_id)
    ).all()
    reserve_balance = connection.scalar(select(GameReserve.balance).where(GameReserve.id == 1))
    if reserve_balance is None:
        raise RuntimeError("The singleton game reserve is missing")
    reserve_journal = connection.scalar(
        select(func.coalesce(func.sum(PointLedgerEntry.delta), 0)).where(
            PointLedgerEntry.reserve_id == 1
        )
    )
    mismatches = tuple(
        BalanceMismatch(account, balance, journal)
        for account, balance, journal in [*rows, (None, reserve_balance, reserve_journal)]
        if balance != journal
    )
    issued = connection.scalar(
        select(func.coalesce(func.sum(PointOperation.amount), 0)).where(
            PointOperation.kind == "OWNER_ISSUE"
        )
    )
    current_supply = sum(balance for _, balance, _ in rows) + reserve_balance
    return ReconciliationReport(mismatches, current_supply, issued)
