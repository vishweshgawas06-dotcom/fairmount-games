"""Internal, all-or-nothing owner password + MFA session issuance.

No HTTP route, cookie, rate limiter or privilege grant is implemented. Caller must
commit before handing the secret token to the owner; a future request boundary must
throttle and audit failures without treating this transaction as public-ready.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import Connection, func, insert, select, update

from fairmount_api.db.models import Account, AccountCredential, AccountSession, SecurityEvent
from fairmount_api.identity.credentials import verify_password
from fairmount_api.identity.mfa_keys import MFAKeyring
from fairmount_api.identity.owner_mfa_verification import (
    OwnerMFAProofUnavailable,
    verify_owner_mfa,
)


class OwnerLoginUnavailable(ValueError):
    """Generic denial; no credential or factor detail is exposed."""


@dataclass(frozen=True)
class IssuedOwnerSession:
    account_id: uuid.UUID
    session_id: uuid.UUID
    token: str = field(repr=False)


def issue_owner_session(
    connection: Connection,
    identifier: str,
    password: str,
    factor_kind: str,
    code: str,
    keyring: MFAKeyring,
) -> IssuedOwnerSession:
    """Prove both factors, replace old session and audit in caller transaction.

    Lock order is Account -> AccountCredential -> OwnerMFA -> recovery code ->
    account_sessions, consistent with factor verification and session resolution.
    Any rollback undoes MFA consumption, revocation, issuance and audit together.
    """
    if identifier != "owner":
        raise OwnerLoginUnavailable("Owner login unavailable")
    owner = connection.execute(
        select(Account.id, Account.status).where(Account.role == "OWNER").with_for_update()
    ).one_or_none()
    if owner is None or owner.status != "ENABLED":
        raise OwnerLoginUnavailable("Owner login unavailable")
    credential = connection.execute(
        select(AccountCredential.password_hash)
        .where(AccountCredential.account_id == owner.id)
        .with_for_update()
    ).one_or_none()
    if credential is None or not verify_password(password, credential.password_hash):
        raise OwnerLoginUnavailable("Owner login unavailable")
    try:
        verified_at = verify_owner_mfa(connection, owner.id, factor_kind, code, keyring)
    except OwnerMFAProofUnavailable as exc:
        raise OwnerLoginUnavailable("Owner login unavailable") from exc
    # The account row lock serializes concurrent owner logins, including changes
    # to credentials/factor/session. Only successful two-factor proof replaces old.
    previous = connection.execute(
        select(AccountSession.id, AccountSession.issued_at)
        .where(AccountSession.account_id == owner.id, AccountSession.revoked_at.is_(None))
        .with_for_update()
    ).one_or_none()
    now = connection.scalar(select(func.clock_timestamp()))
    if previous is not None:
        if now < previous.issued_at:
            raise OwnerLoginUnavailable("Owner login unavailable")
        connection.execute(
            update(AccountSession.__table__)
            .where(AccountSession.id == previous.id)
            .values(revoked_at=now)
        )
    if now < verified_at:
        raise OwnerLoginUnavailable("Owner login unavailable")
    absolute_deadline = verified_at + timedelta(hours=8)
    if now > absolute_deadline:
        raise OwnerLoginUnavailable("Owner login unavailable")
    raw_token = secrets.token_urlsafe(32)
    session_id = connection.execute(
        insert(AccountSession.__table__)
        .values(
            account_id=owner.id,
            role_at_issue="OWNER",
            token_digest=hashlib.sha256(raw_token.encode("ascii")).hexdigest(),
            issued_at=verified_at,
            last_seen_at=now,
            idle_expires_at=min(now + timedelta(minutes=15), absolute_deadline),
            absolute_expires_at=absolute_deadline,
            mfa_verified_at=verified_at,
        )
        .returning(AccountSession.id)
    ).scalar_one()
    connection.execute(
        insert(SecurityEvent.__table__).values(
            event_type="OWNER_SESSION_STARTED",
            source="SELF_SERVICE",
            actor_account_id=owner.id,
            target_account_id=owner.id,
            occurred_at=now,
        )
    )
    return IssuedOwnerSession(account_id=owner.id, session_id=session_id, token=raw_token)
