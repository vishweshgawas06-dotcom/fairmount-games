"""Private player-specific all-or-nothing previous-round rebet.

No HTTP route. Caller owns and commits the transaction; internal SAVEPOINT keeps
an entire bundle atomic even when a caller catches a rejection. Accepted bets
remain immutable and are never modified in place. No client-provided bet list.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, func, insert, select
from sqlalchemy.exc import DBAPIError

from fairmount_api.db.models import (
    AccountWallet,
    GameReserve,
    PointLedgerEntry,
    PointOperation,
    RouletteBet,
    RouletteRound,
)
from fairmount_api.identity.session_validation import resolve_session
from fairmount_api.reserve_coverage import project_round_exposure, reserve_can_accept
from fairmount_api.roulette.admission import AcceptedBet
from fairmount_api.roulette.caps import (
    PER_NUMBER_CAP,
    PER_SELECTION_CAP,
    accepted_amount,
    validate_stake,
)
from fairmount_api.roulette.catalogue import parse_selection_key

_MAX_POINTS = 2**63 - 1


class RebetUnavailable(ValueError):
    """Generic internal rejection, without another player's data or balance."""


class RebetConflict(RebetUnavailable):
    """An actor-scoped idempotency key was already used for another round."""


@dataclass(frozen=True)
class RebetResult:
    source_round_id: uuid.UUID
    target_round_id: uuid.UUID
    bets: tuple[AcceptedBet, ...]
    replayed: bool


def _keys(raw_key: str, count: int) -> tuple[str, ...]:
    # Fixed-length derived item keys also make replay distinguishable from the
    # player's ordinary bet keys in normal clients. The actor Account lock
    # serializes both paths; a deliberately colliding direct bet is rejected.
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return tuple(f"rebet:{digest}:{i}" for i in range(count))


def repeat_previous_bets(
    connection: Connection,
    raw_player_token: str,
    *,
    target_round_id: uuid.UUID,
    idempotency_key: str,
) -> RebetResult:
    """Repeat every accepted bet from the immediate prior persisted round.

    Lock order: player Account/session -> reserve -> target round -> wallet.
    The prior accepted set is immutable; the target must be OPEN and before its
    DB cutoff for a NEW bundle. A committed same-key confirmation replays even
    after cutoff, with no fresh debit. Every item must fit full caps, balance
    and global POOL-01 as one combined package; no per-item partial acceptance.
    """
    if (
        not isinstance(target_round_id, uuid.UUID)
        or not isinstance(idempotency_key, str)
        or not 0 < len(idempotency_key) <= 128
    ):
        raise RebetUnavailable("Rebet unavailable")
    actor = resolve_session(connection, raw_player_token)
    if actor is None or actor.role != "PLAYER":
        raise RebetUnavailable("Rebet unavailable")
    target_opened = connection.scalar(
        select(RouletteRound.opens_at).where(RouletteRound.id == target_round_id)
    )
    if target_opened is None:
        raise RebetUnavailable("Rebet unavailable")
    source_id = connection.scalar(
        select(RouletteRound.id)
        .where(RouletteRound.opens_at < target_opened)
        .order_by(RouletteRound.opens_at.desc(), RouletteRound.id.desc())
        .limit(1)
    )
    if source_id is None:
        raise RebetUnavailable("No previous accepted bets")
    previous = connection.execute(
        select(RouletteBet.selection_key, RouletteBet.accepted_stake)
        .where(RouletteBet.round_id == source_id, RouletteBet.player_account_id == actor.account_id)
        .order_by(RouletteBet.accepted_at, RouletteBet.id)
    ).all()
    if not previous:
        raise RebetUnavailable("No previous accepted bets")
    selections = [(parse_selection_key(key), validate_stake(stake)) for key, stake in previous]
    keys = _keys(idempotency_key, len(selections))
    existing = connection.scalars(
        select(PointOperation.idempotency_key).where(
            PointOperation.actor_account_id == actor.account_id,
            PointOperation.idempotency_key.in_(keys),
        )
    ).all()
    if existing:
        if set(existing) != set(keys):
            raise RebetConflict("Rebet unavailable")
        # The per-item BET_STAKE fingerprint verifies the exact target, key,
        # selection and full amount. All item operations are one prior bundle.
        from fairmount_api.roulette.admission import BetUnavailable, place_bet

        try:
            bets = tuple(
                place_bet(
                    connection,
                    raw_player_token,
                    round_id=target_round_id,
                    selection_key=selection.key,
                    requested=stake,
                    idempotency_key=key,
                )
                for (selection, stake), key in zip(selections, keys, strict=True)
            )
        except BetUnavailable as exc:
            raise RebetConflict("Rebet unavailable") from exc
        if not all(bet.replayed and bet.accepted == bet.requested for bet in bets):
            raise RebetConflict("Rebet unavailable")
        return RebetResult(source_id, target_round_id, bets, True)

    reserve = connection.execute(
        select(GameReserve.balance).where(GameReserve.id == 1).with_for_update()
    ).scalar_one_or_none()
    round_state = connection.execute(
        select(RouletteRound.state, RouletteRound.opens_at, RouletteRound.closes_at)
        .where(RouletteRound.id == target_round_id)
        .with_for_update()
    ).one_or_none()
    now = connection.scalar(select(func.clock_timestamp()))
    if (
        reserve is None
        or round_state is None
        or round_state.state != "OPEN"
        or not round_state.opens_at <= now < round_state.closes_at
    ):
        raise RebetUnavailable("Betting closed")
    wallet = connection.execute(
        select(AccountWallet.balance)
        .where(AccountWallet.account_id == actor.account_id)
        .with_for_update()
    ).scalar_one_or_none()
    stake_total = sum(stake for _, stake in selections)
    if (
        wallet is None
        or wallet < stake_total
        or stake_total > _MAX_POINTS
        or reserve > _MAX_POINTS - stake_total
    ):
        raise RebetUnavailable("Rebet unavailable")

    current = [
        (parse_selection_key(key), stake)
        for key, stake in connection.execute(
            select(RouletteBet.selection_key, RouletteBet.accepted_stake).where(
                RouletteBet.round_id == target_round_id,
                RouletteBet.player_account_id == actor.account_id,
            )
        )
    ]
    for selection, stake in selections:
        if selection.uses_number_cap:
            remaining = [
                PER_NUMBER_CAP
                - sum(
                    amount
                    for prior, amount in current
                    if prior.uses_number_cap and number in prior.numbers
                )
                for number in selection.numbers
            ]
        else:
            remaining = [
                PER_SELECTION_CAP
                - sum(amount for prior, amount in current if prior.key == selection.key)
            ]
        if accepted_amount(stake, remaining) != stake:
            raise RebetUnavailable("Rebet caps unavailable")
        current.append((selection, stake))

    unsettled = connection.scalars(
        select(RouletteRound.id).where(RouletteRound.state.in_(("OPEN", "CLOSED")))
    ).all()
    if target_round_id not in unsettled:
        raise RebetUnavailable("Betting closed")
    buckets = {id_: [] for id_ in unsettled}
    for id_, key, amount in connection.execute(
        select(RouletteBet.round_id, RouletteBet.selection_key, RouletteBet.accepted_stake).where(
            RouletteBet.round_id.in_(unsettled)
        )
    ):
        buckets[id_].append((key, amount))
    buckets[target_round_id].extend((selection.key, stake) for selection, stake in selections)
    exposures = {id_: project_round_exposure(bets) for id_, bets in buckets.items()}
    if not reserve_can_accept(reserve, stake_total, exposures):
        raise RebetUnavailable("Funded reserve unavailable")

    # Savepoint protects the WHOLE package if any insert/trigger fails and the
    # outer caller catches the error before committing its transaction.
    accepted = []
    try:
        with connection.begin_nested():
            for (selection, stake), key in zip(selections, keys, strict=True):
                bet_id = uuid.uuid4()
                fingerprint = hashlib.sha256(
                    json.dumps(
                        (
                            "BET_STAKE",
                            str(actor.account_id),
                            str(target_round_id),
                            selection.key,
                            stake,
                        ),
                        separators=(",", ":"),
                    ).encode("ascii")
                ).hexdigest()
                operation = connection.execute(
                    insert(PointOperation.__table__)
                    .values(
                        kind="BET_STAKE",
                        actor_account_id=actor.account_id,
                        actor_role="PLAYER",
                        source_wallet_id=actor.account_id,
                        target_reserve=True,
                        context_id=bet_id,
                        amount=stake,
                        reason="accepted all-or-nothing roulette rebet",
                        idempotency_key=key,
                        request_fingerprint=fingerprint,
                    )
                    .returning(PointOperation.id)
                ).scalar_one()
                connection.execute(
                    insert(PointLedgerEntry.__table__).values(
                        operation_id=operation, wallet_account_id=actor.account_id, delta=-stake
                    )
                )
                connection.execute(
                    insert(PointLedgerEntry.__table__).values(
                        operation_id=operation, reserve_id=1, delta=stake
                    )
                )
                connection.execute(
                    insert(RouletteBet.__table__).values(
                        id=bet_id,
                        round_id=target_round_id,
                        player_account_id=actor.account_id,
                        operation_id=operation,
                        selection_key=selection.key,
                        accepted_stake=stake,
                    )
                )
                accepted.append(AcceptedBet(bet_id, operation, stake, stake, 0, False))
    except DBAPIError as exc:
        raise RebetUnavailable("Rebet unavailable") from exc
    return RebetResult(source_id, target_round_id, tuple(accepted), False)
