"""Internal session resolution; never call this as a substitute for route authorization.

No session issuer or HTTP cookie boundary exists yet. The caller must finish its
resource-level authorization in the same transaction before acting on this result.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Connection, func, select, update

from fairmount_api.db.models import Account, AccountSession

_TOKEN_FORMAT = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)
_IDLE = {
    "OWNER": timedelta(minutes=15),
    "AGENT": timedelta(minutes=30),
    "PLAYER": timedelta(minutes=30),
}


@dataclass(frozen=True)
class VerifiedSession:
    account_id: uuid.UUID
    session_id: uuid.UUID
    role: str
    mfa_verified_at: datetime | None


def resolve_session(connection: Connection, raw_token: str) -> VerifiedSession | None:
    """Lock account then session; reject expired/revoked/disabled and slide idle expiry.

    Raw token is never persisted or logged. Use inside a transaction. The session
    row and account row remain locked until caller commits/rolls back. There is no
    HTTP authentication endpoint and no authorization policy in this module.
    """
    if not isinstance(raw_token, str) or _TOKEN_FORMAT.fullmatch(raw_token) is None:
        return None
    digest = hashlib.sha256(raw_token.encode("ascii")).hexdigest()
    account_id = connection.scalar(
        select(AccountSession.account_id).where(AccountSession.token_digest == digest)
    )
    if account_id is None:
        return None
    account = connection.execute(
        select(Account.id, Account.role, Account.status)
        .where(Account.id == account_id)
        .with_for_update()
    ).one_or_none()
    if account is None:
        return None
    session = connection.execute(
        select(AccountSession.__table__)
        .where(AccountSession.account_id == account_id, AccountSession.token_digest == digest)
        .with_for_update()
    ).mappings().one_or_none()
    if session is None or session["revoked_at"] is not None:
        return None
    # clock_timestamp() must be read *after* locks, unlike transaction-scoped now().
    now = connection.scalar(select(func.clock_timestamp()))
    if now < session["issued_at"]:
        return None
    if (
        account.status != "ENABLED"
        or now >= session["idle_expires_at"]
        or now >= session["absolute_expires_at"]
        or session["role_at_issue"] != account.role
    ):
        connection.execute(
            update(AccountSession.__table__)
            .where(AccountSession.id == session["id"])
            .values(revoked_at=now)
        )
        return None
    idle_deadline = min(now + _IDLE[account.role], session["absolute_expires_at"])
    connection.execute(
        update(AccountSession.__table__)
        .where(AccountSession.id == session["id"])
        .values(last_seen_at=now, idle_expires_at=idle_deadline)
    )
    return VerifiedSession(
        account_id=account.id,
        session_id=session["id"],
        role=account.role,
        mfa_verified_at=session["mfa_verified_at"],
    )
