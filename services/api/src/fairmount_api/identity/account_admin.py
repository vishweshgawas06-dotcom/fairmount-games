"""Owner-only account lifecycle: assignment and enable/disable, currently internal.

Agents never call these; an agent's authority comes *from* an assignment made
here. Every action re-checks a live owner session with MFA proof no older than
ten minutes, takes its locks in the documented order (owner Account → target
account → assignment row), and appends exactly one audit event that carries no
reason text, address or credential data.

Disabling an account relies on the existing D-03 triggers to revoke its sessions
in the same transaction; this module never issues or clears tokens itself.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Connection, func, insert, select, update

from fairmount_api.db.models import Account, AgentAssignment, SecurityEvent
from fairmount_api.identity.owner_step_up import require_recent_owner_mfa


class AccountAdminUnavailable(ValueError):
    """Generic denial; never distinguish a missing target from a refused one."""


class AccountRow:
    """Minimal locked-account view; keeps call sites from re-declaring tuples."""

    __slots__ = ("id", "role", "status")

    def __init__(self, id: uuid.UUID, role: str, status: str) -> None:
        self.id = id
        self.role = role
        self.status = status


def _require_owner(connection: Connection, raw_owner_token: object) -> uuid.UUID:
    if not isinstance(raw_owner_token, str):
        raise AccountAdminUnavailable("Account change unavailable")
    verified = require_recent_owner_mfa(connection, raw_owner_token)
    if verified is None or verified.role != "OWNER":
        raise AccountAdminUnavailable("Account change unavailable")
    owner = connection.execute(
        select(Account.id, Account.status, Account.role)
        .where(Account.id == verified.account_id)
        .with_for_update()
    ).one_or_none()
    if owner is None or owner.role != "OWNER" or owner.status != "ENABLED":
        raise AccountAdminUnavailable("Account change unavailable")
    return owner.id


def _locked_account(connection: Connection, account_id: object, *, role: str) -> AccountRow:
    if not isinstance(account_id, uuid.UUID):
        raise AccountAdminUnavailable("Account change unavailable")
    row = connection.execute(
        select(Account.id, Account.role, Account.status)
        .where(Account.id == account_id)
        .with_for_update()
    ).one_or_none()
    if row is None or row.role != role:
        raise AccountAdminUnavailable("Account change unavailable")
    return AccountRow(row.id, row.role, row.status)


def _audit(
    connection: Connection,
    *,
    event_type: str,
    actor_id: uuid.UUID,
    target_id: uuid.UUID,
) -> None:
    connection.execute(
        insert(SecurityEvent.__table__).values(
            event_type=event_type,
            source="DASHBOARD",
            actor_account_id=actor_id,
            target_account_id=target_id,
        )
    )


def assign_player(
    connection: Connection, raw_owner_token: str, *, player_id: uuid.UUID, agent_id: uuid.UUID
) -> uuid.UUID:
    """Point one enabled player at one enabled agent, ending any prior assignment.

    Reassignment never leaves two current rows: the existing assignment is closed
    (`ended_at`) before the new one is inserted, and the partial unique index
    remains the database backstop. Returns the new assignment ID.
    """
    owner_id = _require_owner(connection, raw_owner_token)
    player = _locked_account(connection, player_id, role="PLAYER")
    agent = _locked_account(connection, agent_id, role="AGENT")
    if player.status != "ENABLED" or agent.status != "ENABLED":
        raise AccountAdminUnavailable("Account change unavailable")
    now = connection.scalar(select(func.clock_timestamp()))
    current = connection.execute(
        select(AgentAssignment.id, AgentAssignment.agent_account_id)
        .where(
            AgentAssignment.player_account_id == player_id,
            AgentAssignment.ended_at.is_(None),
        )
        .with_for_update()
    ).one_or_none()
    if current is not None and current.agent_account_id == agent_id:
        return current.id  # idempotent: already assigned exactly here
    if current is not None:
        connection.execute(
            update(AgentAssignment.__table__)
            .where(AgentAssignment.id == current.id)
            .values(ended_at=now)
        )
        _audit(
            connection,
            event_type="AGENT_UNASSIGNED",
            actor_id=owner_id,
            target_id=player_id,
        )
    assignment_id = connection.execute(
        insert(AgentAssignment.__table__)
        .values(
            player_account_id=player_id,
            agent_account_id=agent_id,
            actor_account_id=owner_id,
            started_at=now,
        )
        .returning(AgentAssignment.id)
    ).scalar_one()
    _audit(connection, event_type="AGENT_ASSIGNED", actor_id=owner_id, target_id=player_id)
    return assignment_id


def unassign_player(connection: Connection, raw_owner_token: str, *, player_id: uuid.UUID) -> bool:
    """Close the player's current assignment; False when there was none."""
    owner_id = _require_owner(connection, raw_owner_token)
    _locked_account(connection, player_id, role="PLAYER")
    now = connection.scalar(select(func.clock_timestamp()))
    current = connection.execute(
        select(AgentAssignment.id)
        .where(
            AgentAssignment.player_account_id == player_id,
            AgentAssignment.ended_at.is_(None),
        )
        .with_for_update()
    ).one_or_none()
    if current is None:
        return False
    connection.execute(
        update(AgentAssignment.__table__)
        .where(AgentAssignment.id == current.id)
        .values(ended_at=now)
    )
    _audit(connection, event_type="AGENT_UNASSIGNED", actor_id=owner_id, target_id=player_id)
    return True


def set_account_enabled(
    connection: Connection, raw_owner_token: str, *, account_id: uuid.UUID, enabled: bool
) -> str:
    """Enable or disable an AGENT/PLAYER. The sole OWNER can never be disabled here.

    Returns the resulting status. Disablement relies on the D-03 triggers to
    revoke live sessions in the same statement. Assignment rows are history and
    are never rewritten here: authorization reads the account status, so a
    disabled agent cannot act on its players and a disabled player cannot log in.
    """
    owner_id = _require_owner(connection, raw_owner_token)
    if not isinstance(enabled, bool):
        raise AccountAdminUnavailable("Account change unavailable")
    if not isinstance(account_id, uuid.UUID):
        raise AccountAdminUnavailable("Account change unavailable")
    row = connection.execute(
        select(Account.id, Account.role, Account.status)
        .where(Account.id == account_id)
        .with_for_update()
    ).one_or_none()
    if row is None or row.role not in ("AGENT", "PLAYER"):
        raise AccountAdminUnavailable("Account change unavailable")
    desired = "ENABLED" if enabled else "DISABLED"
    if row.status == desired:
        return desired  # idempotent, and no duplicate audit event
    now = connection.scalar(select(func.clock_timestamp()))
    connection.execute(
        update(Account.__table__)
        .where(Account.id == account_id)
        .values(status=desired, disabled_at=None if enabled else now)
    )
    _audit(
        connection,
        event_type="ACCOUNT_ENABLED" if enabled else "ACCOUNT_DISABLED",
        actor_id=owner_id,
        target_id=account_id,
    )
    return desired
