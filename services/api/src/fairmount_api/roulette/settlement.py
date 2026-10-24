"""Private atomic result settlement and full-round void refund primitives.

Caller must own and commit the transaction. No scheduler, public route or
recovery policy is installed; a separate private owner-only surplus-withdrawal
service preserves unresolved liabilities. D-06 decides *when* a void is
permitted; this module does not choose that policy or void on timeout.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import Connection, func, insert, select, update

from fairmount_api.db.models import (
    Account,
    AccountWallet,
    GameReserve,
    PointLedgerEntry,
    PointOperation,
    RouletteBet,
    RouletteRound,
)
from fairmount_api.roulette.catalogue import parse_selection_key
from fairmount_api.roulette.payout import total_payout

_MAX_POINTS = 2**63 - 1


class SettlementUnavailable(ValueError):
    """Do not terminalize a round or silently discard an owed credit."""


@dataclass(frozen=True)
class RoundAccounting:
    round_id: uuid.UUID
    state: str
    total_staked: int
    total_credited: int
    replayed: bool


def settle_round(connection: Connection, round_id: uuid.UUID) -> RoundAccounting:
    """Pay every winning accepted bet at/after reveal from the persisted result.

    Server RNG/result selection is strictly upstream and independent of wagers.
    Never substitute a losing result, partial payout or void for a shortfall.
    """
    return _finish_round(connection, round_id, void=False, reason=None)


def refund_void_round(
    connection: Connection, round_id: uuid.UUID, *, incident_reason: str
) -> RoundAccounting:
    """Trusted recovery primitive only; caller supplies an audited incident.

    Not a public/manual override. D-06a forbids void after result persistence;
    exceptional authorization/triggering still requires a separate decision.
    Includes disabled players' owed refunds.
    """
    if not isinstance(incident_reason, str) or not 0 < len(incident_reason.strip()) <= 300:
        raise SettlementUnavailable("Incident reason required")
    return _finish_round(connection, round_id, void=True, reason=incident_reason.strip())


def _finish_round(
    connection: Connection, round_id: uuid.UUID, *, void: bool, reason: str | None
) -> RoundAccounting:
    if not isinstance(round_id, uuid.UUID):
        raise SettlementUnavailable("Round unavailable")
    # Same global order as admission: reserve -> round -> individual wallets.
    reserve = connection.execute(
        select(GameReserve.balance).where(GameReserve.id == 1).with_for_update()
    ).scalar_one_or_none()
    row = connection.execute(
        select(RouletteRound.state, RouletteRound.winning_number, RouletteRound.reveal_at)
        .where(RouletteRound.id == round_id)
        .with_for_update()
    ).one_or_none()
    if reserve is None or row is None:
        raise SettlementUnavailable("Round unavailable")
    target = "VOID_REFUNDED" if void else "SETTLED"
    if row.state != target:
        if void:
            # D-06a: a persisted winning number must ALWAYS be settled, even
            # after a crash or delayed reveal. No refund may replace it.
            if row.state != "OPEN" or row.winning_number is not None:
                raise SettlementUnavailable("Round unavailable")
        elif (
            row.state != "CLOSED"
            or row.winning_number is None
            or connection.scalar(select(func.clock_timestamp())) < row.reveal_at
        ):
            raise SettlementUnavailable("Round not ready for settlement")

    bets = connection.execute(
        select(RouletteBet.player_account_id, RouletteBet.selection_key, RouletteBet.accepted_stake)
        .where(RouletteBet.round_id == round_id)
        .order_by(RouletteBet.id)
    ).all()
    stakes = sum(bet.accepted_stake for bet in bets)
    if row.state == target:
        credited = connection.scalar(
            select(func.coalesce(func.sum(PointOperation.amount), 0)).where(
                PointOperation.context_id == round_id,
                PointOperation.kind == ("VOID_REFUND" if void else "PAYOUT"),
            )
        )
        return RoundAccounting(round_id, target, stakes, credited, True)

    credits: dict[uuid.UUID, int] = defaultdict(int)
    for bet in bets:
        amount = (
            bet.accepted_stake
            if void
            else total_payout(
                bet.accepted_stake,
                parse_selection_key(bet.selection_key),
                row.winning_number,
            )
        )
        credits[bet.player_account_id] += amount
    owed = sum(credits.values())
    if owed > reserve or owed > _MAX_POINTS or any(v > _MAX_POINTS for v in credits.values()):
        raise SettlementUnavailable("Funded reserve shortfall: preserve unresolved round")

    # No status filter: disabled players retain already-accepted financial claims.
    for player, amount in sorted(credits.items(), key=lambda entry: entry[0].hex):
        if not amount:
            continue
        balance = connection.execute(
            select(AccountWallet.balance)
            .where(AccountWallet.account_id == player)
            .with_for_update()
        ).scalar_one_or_none()
        if balance is None or balance > _MAX_POINTS - amount:
            raise SettlementUnavailable("Payout wallet unavailable: preserve unresolved round")
    owner = connection.scalar(select(Account.id).where(Account.role == "OWNER"))
    if owner is None:
        raise SettlementUnavailable("Accounting actor unavailable")
    kind = "VOID_REFUND" if void else "PAYOUT"
    for player, amount in sorted(credits.items(), key=lambda entry: entry[0].hex):
        if not amount:
            continue
        key = f"{kind.lower()}:{round_id.hex}:{player.hex}"
        fingerprint = hashlib.sha256(
            f"{kind}:{round_id}:{player}:{amount}:{row.winning_number}".encode("ascii")
        ).hexdigest()
        operation = connection.execute(
            insert(PointOperation.__table__)
            .values(
                kind=kind,
                actor_account_id=owner,
                actor_role="OWNER",  # schema-required attribution; internal worker, not owner login
                source_reserve=True,
                target_wallet_id=player,
                context_id=round_id,
                amount=amount,
                reason=reason if void else "automated roulette outcome payout",
                idempotency_key=key,
                request_fingerprint=fingerprint,
            )
            .returning(PointOperation.id)
        ).scalar_one()
        connection.execute(
            insert(PointLedgerEntry.__table__).values(
                operation_id=operation, reserve_id=1, delta=-amount
            )
        )
        connection.execute(
            insert(PointLedgerEntry.__table__).values(
                operation_id=operation, wallet_account_id=player, delta=amount
            )
        )
    connection.execute(
        update(RouletteRound.__table__).where(RouletteRound.id == round_id).values(state=target)
    )
    return RoundAccounting(round_id, target, stakes, owed, False)
