"""Private agent↔currently assigned player transfer, never a public route.

Call under a transaction and commit before reporting success. The request edge
still needs throttling, CSRF/cookie protection and failure audit.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import Connection, insert, select

from fairmount_api.db.models import (
    Account,
    AccountWallet,
    AgentAssignment,
    PointLedgerEntry,
    PointOperation,
)
from fairmount_api.identity.session_validation import resolve_session
from fairmount_api.point_accounting import (
    PointActionConflict,
    PointActionResult,
    PointActionUnavailable,
)

_MAX_POINTS = 2**63 - 1


def transfer_agent_points(
    connection: Connection,
    raw_agent_token: str,
    *,
    player_account_id: uuid.UUID,
    amount: int,
    to_player: bool,
    reason: str,
    idempotency_key: str,
) -> PointActionResult:
    """Fund or return the *entire* amount for one enabled, assigned player.

    Lock order: agent Account/session -> player Account -> current assignment ->
    wallets by UUID. Reassignment and disablement must use a compatible order.
    Ordinary transfers from/to disabled players are forbidden; existing round
    payouts/refunds are a separate system-only service.
    """
    if (
        type(amount) is not int
        or not 1 <= amount <= _MAX_POINTS
        or type(to_player) is not bool
        or not isinstance(player_account_id, uuid.UUID)
        or not isinstance(reason, str)
        or not 0 < len(reason.strip()) <= 500
        or not isinstance(idempotency_key, str)
        or not 0 < len(idempotency_key) <= 128
    ):
        raise PointActionUnavailable("Point action unavailable")
    verified = resolve_session(connection, raw_agent_token)
    if verified is None or verified.role != "AGENT":
        raise PointActionUnavailable("Point action unavailable")
    agent_id = verified.account_id
    source = agent_id if to_player else player_account_id
    target = player_account_id if to_player else agent_id
    canonical_reason = reason.strip()
    fingerprint = hashlib.sha256(
        json.dumps(
            ("AGENT_TRANSFER", str(agent_id), str(source), str(target), amount, canonical_reason),
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    # Locking the agent Account serializes simultaneous requests by this actor.
    previous = connection.execute(
        select(PointOperation.id, PointOperation.request_fingerprint).where(
            PointOperation.actor_account_id == agent_id,
            PointOperation.idempotency_key == idempotency_key,
        )
    ).one_or_none()
    if previous is not None:
        if previous.request_fingerprint != fingerprint:
            raise PointActionConflict("Point action unavailable")
        return PointActionResult(previous.id, replayed=True)
    player = connection.execute(
        select(Account.role, Account.status)
        .where(Account.id == player_account_id)
        .with_for_update()
    ).one_or_none()
    if player is None or player.role != "PLAYER" or player.status != "ENABLED":
        raise PointActionUnavailable("Point action unavailable")
    assigned = connection.execute(
        select(AgentAssignment.id)
        .where(
            AgentAssignment.agent_account_id == agent_id,
            AgentAssignment.player_account_id == player_account_id,
            AgentAssignment.ended_at.is_(None),
        )
        .with_for_update()
    ).one_or_none()
    if assigned is None:
        raise PointActionUnavailable("Point action unavailable")

    balances = {}
    for account_id in sorted((agent_id, player_account_id)):
        wallet = connection.execute(
            select(AccountWallet.balance)
            .where(AccountWallet.account_id == account_id)
            .with_for_update()
        ).scalar_one_or_none()
        if wallet is None:
            raise PointActionUnavailable("Point action unavailable")
        balances[account_id] = wallet
    if balances[source] < amount or balances[target] > _MAX_POINTS - amount:
        raise PointActionUnavailable("Point action unavailable")
    operation_id = connection.execute(
        insert(PointOperation.__table__)
        .values(
            kind="AGENT_TRANSFER",
            actor_account_id=agent_id,
            actor_role="AGENT",
            source_wallet_id=source,
            target_wallet_id=target,
            amount=amount,
            reason=canonical_reason,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
        .returning(PointOperation.id)
    ).scalar_one()
    connection.execute(
        insert(PointLedgerEntry.__table__).values(
            operation_id=operation_id, wallet_account_id=source, delta=-amount
        )
    )
    connection.execute(
        insert(PointLedgerEntry.__table__).values(
            operation_id=operation_id, wallet_account_id=target, delta=amount
        )
    )
    return PointActionResult(operation_id, replayed=False)
