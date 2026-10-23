"""Private, transaction-scoped, role/assignment-filtered point and bet reads.

No HTTP/realtime route exists. The caller must commit the session touch and return
only these projected fields, never raw ORM rows or whole-table client filters.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, select

from fairmount_api.db.models import Account, AccountWallet, AgentAssignment, RouletteBet
from fairmount_api.identity.session_validation import VerifiedSession, resolve_session


class ResourceUnavailable(ValueError):
    """Generic denial: do not distinguish unknown, disabled or unassigned IDs."""


@dataclass(frozen=True)
class WalletView:
    account_id: uuid.UUID
    balance: int


@dataclass(frozen=True)
class PrivateBetView:
    id: uuid.UUID
    round_id: uuid.UUID
    selection_key: str
    accepted_stake: int
    accepted_at: datetime


def _actor(connection: Connection, raw_token: str) -> VerifiedSession:
    verified = resolve_session(connection, raw_token)
    if verified is None:
        raise ResourceUnavailable("Resource unavailable")
    return verified


def _authorize_target(
    connection: Connection,
    actor: VerifiedSession,
    target: uuid.UUID,
    *,
    player_only: bool,
) -> None:
    if not isinstance(target, uuid.UUID):
        raise ResourceUnavailable("Resource unavailable")
    # Account locks pin disablement and role for this transaction. For agents,
    # assignment locks pin current scope until the authorized read completes.
    account = connection.execute(
        select(Account.role, Account.status).where(Account.id == target).with_for_update()
    ).one_or_none()
    if account is None or (player_only and account.role != "PLAYER"):
        raise ResourceUnavailable("Resource unavailable")
    if actor.role == "OWNER":
        return  # Owner can audit a disabled account's existing financial claims.
    if target == actor.account_id:
        if actor.role == "PLAYER" and account.role == "PLAYER":
            return
        if actor.role == "AGENT" and not player_only and account.role == "AGENT":
            return
    if actor.role != "AGENT" or account.role != "PLAYER" or account.status != "ENABLED":
        raise ResourceUnavailable("Resource unavailable")
    current = connection.scalar(
        select(AgentAssignment.id)
        .where(
            AgentAssignment.agent_account_id == actor.account_id,
            AgentAssignment.player_account_id == target,
            AgentAssignment.ended_at.is_(None),
        )
        .with_for_update()
    )
    if current is None:
        raise ResourceUnavailable("Resource unavailable")


def list_visible_player_ids(connection: Connection, raw_token: str) -> tuple[uuid.UUID, ...]:
    """Current enabled player dashboard scope, checked under account/assignment locks.

    Never derive a client-facing roster from historical assignments or a cached
    owner/agent list. A later single-player read must still reauthorize itself.
    """
    actor = _actor(connection, raw_token)
    if actor.role == "PLAYER":
        return (actor.account_id,)
    if actor.role == "OWNER":
        return tuple(
            connection.scalars(
                select(Account.id)
                .where(Account.role == "PLAYER", Account.status == "ENABLED")
                .order_by(Account.id)
                .with_for_update()
            )
        )
    if actor.role != "AGENT":
        raise ResourceUnavailable("Resource unavailable")
    # Candidate assignment IDs are not authorization. Recheck each row *after*
    # locking its player Account, then pin the current assignment until commit.
    candidates = connection.scalars(
        select(AgentAssignment.player_account_id)
        .where(
            AgentAssignment.agent_account_id == actor.account_id,
            AgentAssignment.ended_at.is_(None),
        )
        .order_by(AgentAssignment.player_account_id)
    ).all()
    visible = []
    for player_id in candidates:
        try:
            _authorize_target(connection, actor, player_id, player_only=True)
        except ResourceUnavailable:
            continue
        visible.append(player_id)
    return tuple(visible)


def read_wallet(connection: Connection, raw_token: str, account_id: uuid.UUID) -> WalletView:
    """Owner any wallet; agent own/assigned enabled player; player own only."""
    actor = _actor(connection, raw_token)
    _authorize_target(connection, actor, account_id, player_only=False)
    balance = connection.scalar(
        select(AccountWallet.balance).where(AccountWallet.account_id == account_id)
    )
    if balance is None:
        raise ResourceUnavailable("Resource unavailable")
    return WalletView(account_id, balance)


def read_player_bets(
    connection: Connection, raw_token: str, player_account_id: uuid.UUID
) -> tuple[PrivateBetView, ...]:
    """No cross-player or cross-agent history; disabled history is owner-only."""
    actor = _actor(connection, raw_token)
    _authorize_target(connection, actor, player_account_id, player_only=True)
    rows = connection.execute(
        select(
            RouletteBet.id,
            RouletteBet.round_id,
            RouletteBet.selection_key,
            RouletteBet.accepted_stake,
            RouletteBet.accepted_at,
        )
        .where(RouletteBet.player_account_id == player_account_id)
        .order_by(RouletteBet.accepted_at, RouletteBet.id)
    ).all()
    return tuple(PrivateBetView(*row) for row in rows)
