"""Agent creates a zero-balance player assigned only to itself, never a sub-agent."""

from __future__ import annotations

import uuid

from sqlalchemy import Connection, func, insert, select

from fairmount_api.db.models import AgentAssignment, SecurityEvent
from fairmount_api.identity.identifiers import canonical_player_username
from fairmount_api.identity.provisioning import (
    ProvisionedMember,
    ProvisioningUnavailable,
    _create_member,
    _login_taken,
    validate_profile,
)
from fairmount_api.identity.session_validation import resolve_session


def require_agent(connection: Connection, raw_token: str) -> uuid.UUID:
    """Reauthorize current enabled agent while holding its Account/session locks."""
    verified = resolve_session(connection, raw_token)
    if verified is None or verified.role != "AGENT":
        raise ProvisioningUnavailable("Provisioning unavailable")
    return verified.account_id


def provision_assigned_player(
    connection: Connection,
    raw_agent_token: str,
    *,
    username: str,
    display_name: str,
    mobile_number: str,
) -> ProvisionedMember:
    """Create credential, contact data, zero wallet, assignment and audit atomically.

    The agent ID is derived exclusively from the live session. Neither request
    data nor a preexisting player ID may select scope. Rollback undoes all rows.
    """
    agent_id = require_agent(connection, raw_agent_token)
    validate_profile(display_name, mobile_number)
    try:
        canonical = canonical_player_username(username)
    except ValueError as exc:
        raise ProvisioningUnavailable("Provisioning unavailable") from exc
    if _login_taken(connection, "PLAYER", canonical):
        raise ProvisioningUnavailable("Provisioning unavailable")
    with connection.begin_nested():
        member = _create_member(
            connection,
            agent_id,
            role="PLAYER",
            canonical=canonical,
            display=canonical,
            display_name=display_name,
            mobile_number=mobile_number,
        )
        connection.execute(
            insert(AgentAssignment.__table__).values(
                player_account_id=member.account_id,
                agent_account_id=agent_id,
                actor_account_id=agent_id,
                started_at=connection.scalar(select(func.clock_timestamp())),
            )
        )
        connection.execute(
            insert(SecurityEvent.__table__).values(
                event_type="AGENT_ASSIGNED",
                source="DASHBOARD",
                actor_account_id=agent_id,
                target_account_id=member.account_id,
            )
        )
    return member
