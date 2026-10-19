"""Internal agent/player password session issuance; no public authentication route.

Only activated accounts with fixed canonical identifiers can use this transaction.
The caller commits before returning the raw token. Rate limits, failure accounting,
cookie/CSRF and resource checks remain mandatory before exposing it over HTTP.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import Connection, func, insert, select, update

from fairmount_api.db.models import (
    Account,
    AccountCredential,
    AccountSession,
    PrivateIdentity,
    SecurityEvent,
)
from fairmount_api.identity.credentials import verify_password
from fairmount_api.identity.identifiers import canonical_agent_id, canonical_player_username

_TIMEOUTS = {
    "AGENT": (timedelta(minutes=30), timedelta(hours=12)),
    "PLAYER": (timedelta(minutes=30), timedelta(hours=24)),
}


class MemberLoginUnavailable(ValueError):
    """Generic login denial; do not expose account/credential state."""


@dataclass(frozen=True)
class IssuedMemberSession:
    account_id: uuid.UUID
    session_id: uuid.UUID
    role: str
    token: str = field(repr=False)


def issue_member_session(
    connection: Connection, role: str, identifier: str, password: str
) -> IssuedMemberSession:
    """Verify a role-specific fixed ID/password; atomically replace old session.

    Lookup is not authorization. Lock Account -> Credential -> Session and check
    the current fixed identity again after the account lock. A rollback restores
    prior session, new token row and success audit together.
    """
    try:
        if role == "AGENT":
            canonical = canonical_agent_id(identifier)
        elif role == "PLAYER":
            canonical = canonical_player_username(identifier)
        else:
            raise ValueError("Unsupported role")
    except ValueError as exc:
        raise MemberLoginUnavailable("Login unavailable") from exc
    account_id = connection.scalar(
        select(PrivateIdentity.account_id).where(
            PrivateIdentity.login_kind == role,
            PrivateIdentity.login_identifier == canonical,
        )
    )
    if account_id is None:
        raise MemberLoginUnavailable("Login unavailable")
    account = connection.execute(
        select(Account.id, Account.role, Account.status)
        .where(Account.id == account_id)
        .with_for_update()
    ).one_or_none()
    if account is None or account.role != role or account.status != "ENABLED":
        raise MemberLoginUnavailable("Login unavailable")
    identity_matches = connection.scalar(
        select(PrivateIdentity.account_id).where(
            PrivateIdentity.account_id == account.id,
            PrivateIdentity.login_kind == role,
            PrivateIdentity.login_identifier == canonical,
        )
    )
    if identity_matches is None:
        raise MemberLoginUnavailable("Login unavailable")
    credential = connection.execute(
        select(AccountCredential.password_hash)
        .where(AccountCredential.account_id == account.id)
        .with_for_update()
    ).one_or_none()
    if credential is None or not verify_password(password, credential.password_hash):
        raise MemberLoginUnavailable("Login unavailable")
    previous = connection.execute(
        select(AccountSession.id, AccountSession.issued_at)
        .where(AccountSession.account_id == account.id, AccountSession.revoked_at.is_(None))
        .with_for_update()
    ).one_or_none()
    now = connection.scalar(select(func.clock_timestamp()))
    if previous is not None:
        if now < previous.issued_at:
            raise MemberLoginUnavailable("Login unavailable")
        connection.execute(
            update(AccountSession.__table__)
            .where(AccountSession.id == previous.id)
            .values(revoked_at=now)
        )
    idle, absolute = _TIMEOUTS[role]
    raw_token = secrets.token_urlsafe(32)
    session_id = connection.execute(
        insert(AccountSession.__table__)
        .values(
            account_id=account.id,
            role_at_issue=role,
            token_digest=hashlib.sha256(raw_token.encode("ascii")).hexdigest(),
            issued_at=now,
            last_seen_at=now,
            idle_expires_at=now + idle,
            absolute_expires_at=now + absolute,
            mfa_verified_at=None,
        )
        .returning(AccountSession.id)
    ).scalar_one()
    connection.execute(
        insert(SecurityEvent.__table__).values(
            event_type="MEMBER_SESSION_STARTED",
            source="SELF_SERVICE",
            actor_account_id=account.id,
            target_account_id=account.id,
            occurred_at=now,
        )
    )
    return IssuedMemberSession(
        account_id=account.id, session_id=session_id, role=role, token=raw_token
    )
