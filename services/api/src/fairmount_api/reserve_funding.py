"""Internal owner-wallet → separate game-reserve funding; no withdrawal API.

Must run under the caller's transaction and commit before acknowledging funding.
Future betting/withdrawal services must lock this same reserve row first.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import Connection, insert, select

from fairmount_api.db.models import AccountWallet, GameReserve, PointLedgerEntry, PointOperation
from fairmount_api.identity.owner_step_up import require_recent_owner_mfa
from fairmount_api.point_accounting import (
    PointActionConflict,
    PointActionResult,
    PointActionUnavailable,
)

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

    No implicit issuance, borrowing, direct member-to-reserve transfer or
    reserve withdrawal is implemented. No round-result RNG is consulted.
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
