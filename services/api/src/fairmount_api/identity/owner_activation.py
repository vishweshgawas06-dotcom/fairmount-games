"""Internal initial owner activation, not a route, session or management grant.

The caller owns the transaction. No public interface may call this until request-size
limits, rate limits, secure delivery, MFA enrollment and session gating are reviewed.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Connection, func, insert, select, update

from fairmount_api.db.models import Account, AccountCredential, OwnerMFA, SecurityEvent
from fairmount_api.identity.credentials import hash_password, verify_initial_secret


class OwnerActivationUnavailable(ValueError):
    """Fail closed without distinguishing a missing account, bad token or expiry."""


def activate_initial_owner(connection: Connection, secret: str, new_password: str) -> uuid.UUID:
    """Consume one valid pending secret and store the Argon2id password atomically.

    Lock Account before AccountCredential (the same order as pre-activation reissue).
    On success the owner is still NOT authorized: confirmed MFA/session required.
    """
    owner = connection.execute(
        select(Account.id, Account.status)
        .where(Account.role == "OWNER")
        .with_for_update()
    ).one_or_none()
    if owner is None or owner.status != "ENABLED":
        raise OwnerActivationUnavailable("Owner activation unavailable")
    credential = connection.execute(
        select(
            AccountCredential.initial_secret_digest,
            AccountCredential.initial_secret_expires_at,
            AccountCredential.password_hash,
            AccountCredential.initial_secret_consumed_at,
        )
        .where(AccountCredential.account_id == owner.id)
        .with_for_update()
    ).one_or_none()
    if (
        credential is None
        or credential.password_hash is not None
        or credential.initial_secret_consumed_at is not None
        or credential.initial_secret_digest is None
        or credential.initial_secret_expires_at is None
        or connection.scalar(select(OwnerMFA.account_id).where(OwnerMFA.account_id == owner.id))
        is not None
        or not verify_initial_secret(secret, credential.initial_secret_digest)
    ):
        raise OwnerActivationUnavailable("Owner activation unavailable")

    # First reject an already expired secret before performing expensive hashing.
    if connection.scalar(select(func.clock_timestamp())) >= credential.initial_secret_expires_at:
        raise OwnerActivationUnavailable("Owner activation unavailable")
    password_hash = hash_password(new_password)
    # Check again after hashing; a secret that expires mid-request must not succeed.
    now = connection.scalar(select(func.clock_timestamp()))
    if now >= credential.initial_secret_expires_at:
        raise OwnerActivationUnavailable("Owner activation unavailable")
    connection.execute(
        update(AccountCredential.__table__)
        .where(AccountCredential.account_id == owner.id)
        .values(
            initial_secret_digest=None,
            initial_secret_expires_at=None,
            initial_secret_consumed_at=now,
            password_hash=password_hash,
            password_changed_at=now,
        )
    )
    connection.execute(
        insert(SecurityEvent.__table__).values(
            event_type="INITIAL_CREDENTIAL_CONSUMED",
            source="SELF_SERVICE",
            actor_account_id=owner.id,
            target_account_id=owner.id,
        )
    )
    return owner.id
