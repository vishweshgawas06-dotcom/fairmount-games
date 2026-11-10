"""Bounded operator projections; no gameplay P/L or credential/contact export.

Every read authenticates from the live session. Candidate identifiers and cursor
values never grant scope. Agent rows are reauthorized under account/assignment
locks, including historical transfers, before any private fields leave the DB.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import Connection, func, select, tuple_

from fairmount_api.db.models import (
    Account,
    AccountCredential,
    AccountWallet,
    AgentAssignment,
    GameReserve,
    PointOperation,
    PrivateIdentity,
)
from fairmount_api.identity.owner_step_up import OWNER_STEP_UP_MAX_AGE
from fairmount_api.identity.session_validation import resolve_session
from fairmount_api.resource_reads import ResourceUnavailable, _authorize_target

PAGE_SIZE = 50
ADMIN_KINDS = (
    "OWNER_ISSUE",
    "OWNER_TRANSFER",
    "AGENT_TRANSFER",
    "RESERVE_FUND",
    "RESERVE_WITHDRAW",
    "AGENT_DISABLE_RETURN",
)


def _operator(connection: Connection, token: str):
    actor = resolve_session(connection, token, touch_idle=False)
    if actor is None or actor.role not in ("OWNER", "AGENT"):
        raise ResourceUnavailable("Resource unavailable")
    return actor


def read_context(connection: Connection, token: str) -> dict:
    actor = _operator(connection, token)
    now = connection.scalar(select(func.clock_timestamp()))
    balance = connection.scalar(
        select(AccountWallet.balance).where(AccountWallet.account_id == actor.account_id)
    )
    if balance is None:
        raise ResourceUnavailable("Resource unavailable")
    payload = {
        "account_id": str(actor.account_id),
        "role": actor.role,
        "balance": str(balance),
        "observed_at": now.isoformat(),
        "mfa_refresh_required": actor.role == "OWNER"
        and (
            actor.mfa_verified_at is None
            or not actor.mfa_verified_at <= now <= actor.mfa_verified_at + OWNER_STEP_UP_MAX_AGE
        ),
    }
    if actor.role == "OWNER":
        payload["reserve_balance"] = str(connection.scalar(select(GameReserve.balance)))
    return payload


def read_members(connection: Connection, token: str, after: uuid.UUID | None = None) -> dict:
    actor = _operator(connection, token)
    query = select(Account.id).where(Account.role.in_(("AGENT", "PLAYER")))
    if actor.role == "AGENT":
        query = query.join(AgentAssignment, AgentAssignment.player_account_id == Account.id).where(
            Account.role == "PLAYER",
            Account.status == "ENABLED",
            AgentAssignment.agent_account_id == actor.account_id,
            AgentAssignment.ended_at.is_(None),
        )
    if after is not None:
        query = query.where(Account.id > after)
    candidates = connection.scalars(query.order_by(Account.id).limit(PAGE_SIZE + 1)).all()
    items = []
    for target in candidates[:PAGE_SIZE]:
        try:
            _authorize_target(connection, actor, target, player_only=actor.role == "AGENT")
        except ResourceUnavailable:
            continue
        row = connection.execute(
            select(
                Account.id,
                Account.role,
                Account.status,
                PrivateIdentity.login_identifier,
                PrivateIdentity.display_name,
                AccountWallet.balance,
                (
                    AccountCredential.account_id.is_not(None)
                    & AccountCredential.password_hash.is_(None)
                ).label("activation_pending"),
            )
            .join(AccountWallet, AccountWallet.account_id == Account.id)
            .outerjoin(PrivateIdentity, PrivateIdentity.account_id == Account.id)
            .outerjoin(AccountCredential, AccountCredential.account_id == Account.id)
            .where(Account.id == target)
        ).one()
        assignment = connection.scalar(
            select(AgentAssignment.agent_account_id).where(
                AgentAssignment.player_account_id == target, AgentAssignment.ended_at.is_(None)
            )
        )
        items.append(
            {
                "account_id": str(row.id),
                "role": row.role,
                "status": row.status,
                "identifier": row.login_identifier.upper()
                if row.role == "AGENT" and row.login_identifier
                else row.login_identifier,
                "display_name": row.display_name,
                "activation_pending": bool(row.activation_pending),
                "balance": str(row.balance),
                "agent_account_id": str(assignment) if assignment else None,
            }
        )
    return {
        "items": items,
        "next_after": str(candidates[PAGE_SIZE - 1]) if len(candidates) > PAGE_SIZE else None,
    }


def encode_cursor(created_at: datetime, operation_id: uuid.UUID) -> str:
    raw = json.dumps([created_at.astimezone(UTC).isoformat(), str(operation_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value: str) -> tuple[datetime, uuid.UUID]:
    if not isinstance(value, str) or not 1 <= len(value) <= 160:
        raise ValueError("Invalid cursor")
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        parts = json.loads(raw)
        if (
            not isinstance(parts, list)
            or len(parts) != 2
            or any(not isinstance(p, str) for p in parts)
        ):
            raise ValueError("Invalid cursor")
        when, operation = datetime.fromisoformat(parts[0]), uuid.UUID(parts[1])
        if when.tzinfo is None or encode_cursor(when, operation) != value:
            raise ValueError("Invalid cursor")
        return when, operation
    except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
        raise ValueError("Invalid cursor") from exc


def read_history(connection: Connection, token: str, after=None) -> dict:
    actor = _operator(connection, token)
    query = select(PointOperation).where(PointOperation.kind.in_(ADMIN_KINDS))
    if actor.role == "AGENT":
        query = query.where(
            PointOperation.actor_account_id == actor.account_id,
            PointOperation.kind == "AGENT_TRANSFER",
        )
    if after is not None:
        query = query.where(tuple_(PointOperation.created_at, PointOperation.id) < after)
    rows = connection.execute(
        query.order_by(PointOperation.created_at.desc(), PointOperation.id.desc()).limit(
            PAGE_SIZE + 1
        )
    ).all()
    items = []
    for row in rows[:PAGE_SIZE]:
        if actor.role == "AGENT":
            target = (
                row.target_wallet_id
                if row.source_wallet_id == actor.account_id
                else (row.source_wallet_id)
            )
            try:
                _authorize_target(connection, actor, target, player_only=True)
            except ResourceUnavailable:
                continue
        items.append(
            {
                "operation_id": str(row.id),
                "kind": row.kind,
                "amount": str(row.amount),
                "reason": row.reason,
                "created_at": row.created_at.isoformat(),
                "actor_account_id": str(row.actor_account_id),
                "source": "reserve"
                if row.source_reserve
                else str(row.source_wallet_id)
                if row.source_wallet_id
                else "issuance",
                "target": "reserve" if row.target_reserve else str(row.target_wallet_id),
            }
        )
    return {
        "items": items,
        "next_after": encode_cursor(rows[PAGE_SIZE - 1].created_at, rows[PAGE_SIZE - 1].id)
        if len(rows) > PAGE_SIZE
        else None,
    }
