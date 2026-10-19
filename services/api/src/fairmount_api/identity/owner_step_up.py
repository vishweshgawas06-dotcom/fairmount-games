"""Internal owner MFA recency and session-bound step-up; no privileged route.

A future sensitive action must check freshness AND authorize its resource under the
same DB transaction. Failure accounting and rate limits belong at the request edge.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import Connection, func, select, update

from fairmount_api.db.models import AccountSession
from fairmount_api.identity.mfa_keys import MFAKeyring
from fairmount_api.identity.owner_mfa_verification import (
    OwnerMFAProofUnavailable,
    verify_owner_mfa,
)
from fairmount_api.identity.session_validation import VerifiedSession, resolve_session

OWNER_STEP_UP_MAX_AGE = timedelta(minutes=10)
OWNER_IDLE_TIMEOUT = timedelta(minutes=15)


def require_recent_owner_mfa(connection: Connection, raw_token: str) -> VerifiedSession | None:
    """Fail closed if no enabled live owner session with MFA no older than 10m.

    This is only a factor/session prerequisite, NOT an owner-action authorization.
    The caller must keep account/session locks until the action finishes or fails.
    """
    verified = resolve_session(connection, raw_token)
    if verified is None or verified.role != "OWNER" or verified.mfa_verified_at is None:
        return None
    now = connection.scalar(select(func.clock_timestamp()))
    if not verified.mfa_verified_at <= now <= verified.mfa_verified_at + OWNER_STEP_UP_MAX_AGE:
        return None
    return verified


def step_up_owner_session(
    connection: Connection,
    raw_token: str,
    factor_kind: str,
    code: str,
    keyring: MFAKeyring,
) -> VerifiedSession:
    """Verify another factor for an existing live owner session, without new token.

    `resolve_session` locks Account then session. Since all owner login/step-up
    transactions lock the sole Account first, factor and session updates serialize.
    Any rollback restores the consumed factor, timestamp, idle touch and audit.
    """
    verified = resolve_session(connection, raw_token)
    if verified is None or verified.role != "OWNER":
        raise OwnerMFAProofUnavailable("Owner MFA proof unavailable")
    verified_at = verify_owner_mfa(connection, verified.account_id, factor_kind, code, keyring)
    row = connection.execute(
        select(AccountSession.absolute_expires_at, AccountSession.idle_expires_at)
        .where(AccountSession.id == verified.session_id)
        .with_for_update()
    ).one()
    now = connection.scalar(select(func.clock_timestamp()))
    if now < verified_at or now >= row.idle_expires_at or now >= row.absolute_expires_at:
        raise OwnerMFAProofUnavailable("Owner MFA proof unavailable")
    connection.execute(
        update(AccountSession.__table__)
        .where(AccountSession.id == verified.session_id)
        .values(
            mfa_verified_at=verified_at,
            last_seen_at=now,
            idle_expires_at=min(now + OWNER_IDLE_TIMEOUT, row.absolute_expires_at),
        )
    )
    return VerifiedSession(
        account_id=verified.account_id,
        session_id=verified.session_id,
        role="OWNER",
        mfa_verified_at=verified_at,
    )
