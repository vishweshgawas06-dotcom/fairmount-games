"""Internal bearer-possession logout; no HTTP endpoint or cookie clearing yet.

A future browser route MUST require CSRF protection and clear its cookie. The
caller commits before acknowledging logout. Do not use this as action authority.
"""

from __future__ import annotations

from sqlalchemy import Connection, func, insert, select, update

from fairmount_api.db.models import Account, AccountSession, SecurityEvent
from fairmount_api.identity.session_validation import session_token_digest


def revoke_presented_session(connection: Connection, raw_token: str) -> bool:
    """Revoke one presented session under Account -> Session locks, even if expired.

    Returns False for malformed, absent or already-revoked tokens. A token is
    never logged; its SHA-256 digest is used only for a lookup. The audit actor
    represents bearer possession, not an MFA-fresh owner action.
    """
    digest = session_token_digest(raw_token)
    if digest is None:
        return False
    account_id = connection.scalar(
        select(AccountSession.account_id).where(AccountSession.token_digest == digest)
    )
    if account_id is None:
        return False
    account = connection.execute(
        select(Account.id).where(Account.id == account_id).with_for_update()
    ).one_or_none()
    if account is None:
        return False
    session = connection.execute(
        select(AccountSession.id, AccountSession.issued_at, AccountSession.revoked_at)
        .where(AccountSession.account_id == account_id, AccountSession.token_digest == digest)
        .with_for_update()
    ).one_or_none()
    if session is None or session.revoked_at is not None:
        return False
    now = connection.scalar(select(func.clock_timestamp()))
    connection.execute(
        update(AccountSession.__table__)
        .where(AccountSession.id == session.id)
        .values(revoked_at=max(now, session.issued_at))
    )
    connection.execute(
        insert(SecurityEvent.__table__).values(
            event_type="SESSION_REVOKED",
            source="SELF_SERVICE",
            actor_account_id=account.id,
            target_account_id=account.id,
            occurred_at=now,
        )
    )
    return True
