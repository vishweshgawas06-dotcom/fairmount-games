"""Internal owner↔reserve transfers; never issue or borrow reserve points.

Must run under a caller-owned transaction and commit before acknowledging. Both
services lock the same global reserve before any affected wallet. No HTTP route.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import Connection, insert, select

from fairmount_api.db.models import (
    AccountWallet,
    GameReserve,
    PointLedgerEntry,
    PointOperation,
    RouletteBet,
    RouletteRound,
)
from fairmount_api.identity.owner_step_up import require_recent_owner_mfa
from fairmount_api.point_accounting import (
    PointActionConflict,
    PointActionResult,
    PointActionUnavailable,
)
from fairmount_api.reserve_coverage import project_round_exposure, required_reserve

_MAX_POINTS = 2**63 - 1


def fund_game_reserve(
    connection: Connection,
    raw_owner_token: str,
    *,
    amount: int,
    reason: str,
    idempotency_key: str,
) -> PointActionResult:
    """Conserve points from owner wallet into the singleton funded reserve.

    No implicit issuance, borrowing or direct member-to-reserve transfer.
    No round-result RNG is consulted.
    """
    if (
        type(amount) is not int
        or not 1 <= amount <= _MAX_POINTS
        or not isinstance(reason, str)
        or not 0 < len(reason.strip()) <= 500
        or not isinstance(idempotency_key, str)
        or not 0 < len(idempotency_key) <= 128
    ):
        raise PointActionUnavailable("Point action unavailable")
    verified = require_recent_owner_mfa(connection, raw_owner_token)
    if verified is None:
        raise PointActionUnavailable("Point action unavailable")
    owner = verified.account_id
    canonical_reason = reason.strip()
    fingerprint = hashlib.sha256(
        json.dumps(
            ("RESERVE_FUND", str(owner), str(owner), "reserve:1", amount, canonical_reason),
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    # The sole owner Account lock serializes same-key retries by this actor.
    previous = connection.execute(
        select(PointOperation.id, PointOperation.request_fingerprint).where(
            PointOperation.actor_account_id == owner,
            PointOperation.idempotency_key == idempotency_key,
        )
    ).one_or_none()
    if previous is not None:
        if previous.request_fingerprint != fingerprint:
            raise PointActionConflict("Point action unavailable")
        return PointActionResult(previous.id, replayed=True)
    # Global order for future bet/settlement transactions: reserve first, then
    # affected wallet(s). Never lock owner wallet and then wait for reserve.
    reserve_balance = connection.execute(
        select(GameReserve.balance).where(GameReserve.id == 1).with_for_update()
    ).scalar_one_or_none()
    owner_balance = connection.execute(
        select(AccountWallet.balance).where(AccountWallet.account_id == owner).with_for_update()
    ).scalar_one_or_none()
    if (
        reserve_balance is None
        or owner_balance is None
        or owner_balance < amount
        or reserve_balance > _MAX_POINTS - amount
    ):
        raise PointActionUnavailable("Point action unavailable")
    operation_id = connection.execute(
        insert(PointOperation.__table__)
        .values(
            kind="RESERVE_FUND",
            actor_account_id=owner,
            actor_role="OWNER",
            source_wallet_id=owner,
            target_reserve=True,
            amount=amount,
            reason=canonical_reason,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
        .returning(PointOperation.id)
    ).scalar_one()
    connection.execute(
        insert(PointLedgerEntry.__table__).values(
            operation_id=operation_id, wallet_account_id=owner, delta=-amount
        )
    )
    connection.execute(
        insert(PointLedgerEntry.__table__).values(
            operation_id=operation_id, reserve_id=1, delta=amount
        )
    )
    return PointActionResult(operation_id, replayed=False)


def withdraw_surplus_reserve(
    connection: Connection,
    raw_owner_token: str,
    *,
    amount: int,
    reason: str,
    idempotency_key: str,
) -> PointActionResult:
    """Move only proven surplus back to owner, retaining every unsettled claim.

    The global reserve lock serializes bets, terminal credits, funding and
    withdrawals. Rebuild POOL-01 obligations from immutable accepted bets for
    all OPEN/CLOSED rounds. Keep full void refunds even after result persistence;
    a recovery policy has not been chosen. No partial withdrawal or owner issue.
    """
    if (
        type(amount) is not int
        or not 1 <= amount <= _MAX_POINTS
        or not isinstance(reason, str)
        or not 0 < len(reason.strip()) <= 500
        or not isinstance(idempotency_key, str)
        or not 0 < len(idempotency_key) <= 128
    ):
        raise PointActionUnavailable("Point action unavailable")
    verified = require_recent_owner_mfa(connection, raw_owner_token)
    if verified is None:
        raise PointActionUnavailable("Point action unavailable")
    owner = verified.account_id
    canonical_reason = reason.strip()
    fingerprint = hashlib.sha256(
        json.dumps(
            ("RESERVE_WITHDRAW", str(owner), "reserve:1", str(owner), amount, canonical_reason),
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    # Sole owner Account lock serializes actor-scoped retries before funds move.
    previous = connection.execute(
        select(PointOperation.id, PointOperation.kind, PointOperation.request_fingerprint).where(
            PointOperation.actor_account_id == owner,
            PointOperation.idempotency_key == idempotency_key,
        )
    ).one_or_none()
    if previous is not None:
        if previous.kind != "RESERVE_WITHDRAW" or previous.request_fingerprint != fingerprint:
            raise PointActionConflict("Point action unavailable")
        return PointActionResult(previous.id, replayed=True)

    reserve_balance = connection.execute(
        select(GameReserve.balance).where(GameReserve.id == 1).with_for_update()
    ).scalar_one_or_none()
    if reserve_balance is None or reserve_balance < amount:
        raise PointActionUnavailable("Point action unavailable")
    unsettled_ids = connection.scalars(
        select(RouletteRound.id).where(RouletteRound.state.in_(("OPEN", "CLOSED")))
    ).all()
    buckets = {round_id: [] for round_id in unsettled_ids}
    if unsettled_ids:
        for round_id, key, stake in connection.execute(
            select(
                RouletteBet.round_id, RouletteBet.selection_key, RouletteBet.accepted_stake
            ).where(RouletteBet.round_id.in_(unsettled_ids))
        ):
            buckets[round_id].append((key, stake))
    exposures = {round_id: project_round_exposure(bets) for round_id, bets in buckets.items()}
    if reserve_balance - amount < required_reserve(exposures):
        raise PointActionUnavailable("Point action unavailable")
    owner_balance = connection.execute(
        select(AccountWallet.balance).where(AccountWallet.account_id == owner).with_for_update()
    ).scalar_one_or_none()
    if owner_balance is None or owner_balance > _MAX_POINTS - amount:
        raise PointActionUnavailable("Point action unavailable")
    operation_id = connection.execute(
        insert(PointOperation.__table__)
        .values(
            kind="RESERVE_WITHDRAW",
            actor_account_id=owner,
            actor_role="OWNER",
            source_reserve=True,
            target_wallet_id=owner,
            amount=amount,
            reason=canonical_reason,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
        .returning(PointOperation.id)
    ).scalar_one()
    connection.execute(
        insert(PointLedgerEntry.__table__).values(
            operation_id=operation_id, reserve_id=1, delta=-amount
        )
    )
    connection.execute(
        insert(PointLedgerEntry.__table__).values(
            operation_id=operation_id, wallet_account_id=owner, delta=amount
        )
    )
    return PointActionResult(operation_id, replayed=False)
