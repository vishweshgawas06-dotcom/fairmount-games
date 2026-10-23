"""Private, PostgreSQL-serialized bet admission under owner-approved POOL-01.

Caller owns the transaction and must commit before confirming acceptance. No
public betting endpoint or recovery worker. Terminal accounting and protected
owner surplus withdrawal exist separately but are not wired to public routes.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, func, insert, select

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
from fairmount_api.roulette.caps import (
    PER_NUMBER_CAP,
    PER_SELECTION_CAP,
    accepted_amount,
    validate_stake,
)
from fairmount_api.roulette.catalogue import parse_selection_key

_MAX_POINTS = 2**63 - 1


class BetUnavailable(ValueError):
    """Safe internal rejection; no wallet/identity details leave this module."""


class BetReplayConflict(BetUnavailable):
    """An idempotency key was used for a different request."""


@dataclass(frozen=True)
class AcceptedBet:
    bet_id: uuid.UUID
    operation_id: uuid.UUID
    requested: int
    accepted: int
    unaccepted: int  # never debited; not a second credit or refund
    replayed: bool


def place_bet(
    connection: Connection,
    raw_player_token: str,
    *,
    round_id: uuid.UUID,
    selection_key: str,
    requested: int,
    idempotency_key: str,
) -> AcceptedBet:
    """Atomic in the caller's transaction; no reserve-limited partial stake.

    Lock order: player Account/session -> global reserve -> round -> player wallet.
    Every betting/settlement/withdrawal service must acquire the same reserve
    before any round/wallet rows. The round's DB trigger rechecks cutoff on
    insertion and prevents a close transition racing with a bet commit.
    """
    selection = parse_selection_key(selection_key)
    validate_stake(requested)
    if (
        requested > _MAX_POINTS
        or not isinstance(round_id, uuid.UUID)
        or not isinstance(idempotency_key, str)
        or not 0 < len(idempotency_key) <= 128
    ):
        raise BetUnavailable("Bet unavailable")
    verified = resolve_session(connection, raw_player_token)
    if verified is None or verified.role != "PLAYER":
        raise BetUnavailable("Bet unavailable")
    player_id = verified.account_id
    fingerprint = hashlib.sha256(
        json.dumps(
            ("BET_STAKE", str(player_id), str(round_id), selection.key, requested),
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    previous = connection.execute(
        select(PointOperation.id, PointOperation.kind, PointOperation.request_fingerprint).where(
            PointOperation.actor_account_id == player_id,
            PointOperation.idempotency_key == idempotency_key,
        )
    ).one_or_none()
    if previous is not None:
        if previous.kind != "BET_STAKE" or previous.request_fingerprint != fingerprint:
            raise BetReplayConflict("Bet unavailable")
        prior_bet = connection.execute(
            select(RouletteBet.id, RouletteBet.accepted_stake).where(
                RouletteBet.operation_id == previous.id
            )
        ).one_or_none()
        if prior_bet is None:
            raise BetUnavailable("Bet unavailable")
        return AcceptedBet(
            prior_bet.id,
            previous.id,
            requested,
            prior_bet.accepted_stake,
            requested - prior_bet.accepted_stake,
            True,
        )
    balance = connection.execute(
        select(GameReserve.balance).where(GameReserve.id == 1).with_for_update()
    ).scalar_one_or_none()
    if balance is None:
        raise BetUnavailable("Funded reserve unavailable")
    round_state = connection.execute(
        select(RouletteRound.state, RouletteRound.opens_at, RouletteRound.closes_at)
        .where(RouletteRound.id == round_id)
        .with_for_update()
    ).one_or_none()
    now = connection.scalar(select(func.clock_timestamp()))
    if (
        round_state is None
        or round_state.state != "OPEN"
        or not round_state.opens_at <= now < round_state.closes_at
    ):
        raise BetUnavailable("Betting closed")
    wallet = connection.execute(
        select(AccountWallet.balance).where(AccountWallet.account_id == player_id).with_for_update()
    ).scalar_one_or_none()
    # The FULL requested stake must be affordable before cap-limited partial acceptance.
    if wallet is None or wallet < requested:
        raise BetUnavailable("Insufficient points for the full requested stake")
    current = connection.execute(
        select(RouletteBet.selection_key, RouletteBet.accepted_stake).where(
            RouletteBet.round_id == round_id, RouletteBet.player_account_id == player_id
        )
    ).all()
    parsed = [(parse_selection_key(key), stake) for key, stake in current]
    if selection.uses_number_cap:
        remaining = [
            PER_NUMBER_CAP
            - sum(
                stake
                for prior, stake in parsed
                if prior.uses_number_cap and number in prior.numbers
            )
            for number in sorted(selection.numbers)
        ]
    else:
        remaining = [
            PER_SELECTION_CAP - sum(stake for prior, stake in parsed if prior.key == selection.key)
        ]
    accepted = accepted_amount(requested, remaining)
    if accepted == 0:
        raise BetUnavailable("Selection cap reached")
    if balance > _MAX_POINTS - accepted:
        raise BetUnavailable("Funded reserve unavailable")

    # Rebuild every unsettled round from DB-accepted bets, never client vectors.
    unsettled_ids = connection.scalars(
        select(RouletteRound.id).where(RouletteRound.state.in_(("OPEN", "CLOSED")))
    ).all()
    if round_id not in unsettled_ids:
        raise BetUnavailable("Betting closed")
    buckets = {id_: [] for id_ in unsettled_ids}
    for id_, key, stake in connection.execute(
        select(RouletteBet.round_id, RouletteBet.selection_key, RouletteBet.accepted_stake).where(
            RouletteBet.round_id.in_(unsettled_ids)
        )
    ):
        buckets[id_].append((key, stake))
    buckets[round_id].append((selection.key, accepted))  # exactly once
    exposures = {id_: project_round_exposure(bets) for id_, bets in buckets.items()}
    if not reserve_can_accept(balance, accepted, exposures):
        raise BetUnavailable("Funded reserve unavailable")

    bet_id = uuid.uuid4()
    operation_id = connection.execute(
        insert(PointOperation.__table__)
        .values(
            kind="BET_STAKE",
            actor_account_id=player_id,
            actor_role="PLAYER",
            source_wallet_id=player_id,
            target_reserve=True,
            context_id=bet_id,
            amount=accepted,
            reason="accepted roulette stake",
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
        .returning(PointOperation.id)
    ).scalar_one()
    connection.execute(
        insert(PointLedgerEntry.__table__).values(
            operation_id=operation_id, wallet_account_id=player_id, delta=-accepted
        )
    )
    connection.execute(
        insert(PointLedgerEntry.__table__).values(
            operation_id=operation_id, reserve_id=1, delta=accepted
        )
    )
    # The DB trigger overwrites accepted_at with server clock and rechecks cutoff.
    connection.execute(
        insert(RouletteBet.__table__).values(
            id=bet_id,
            round_id=round_id,
            player_account_id=player_id,
            operation_id=operation_id,
            selection_key=selection.key,
            accepted_stake=accepted,
        )
    )
    return AcceptedBet(bet_id, operation_id, requested, accepted, requested - accepted, False)
