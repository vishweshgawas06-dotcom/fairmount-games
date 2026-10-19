"""Internal owner bootstrap transactions; not an API, CLI or authentication flow.

The caller MUST commit successfully before delivering the returned secret. Only a
future owner-run local command may call these functions; database access and an
owner-controlled terminal remain prerequisites. No management access is created.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, func, insert, select, text, update

from fairmount_api.db.models import Account, AccountCredential, OwnerMFA, SecurityEvent
from fairmount_api.identity.credentials import generate_initial_secret, initial_secret_digest


@dataclass(frozen=True)
class PendingOwnerSecret:
    account_id: uuid.UUID
    secret: str = field(repr=False)


def _record_owner_event(connection: Connection, owner_id: uuid.UUID, event_type: str) -> None:
    connection.execute(
        insert(SecurityEvent.__table__).values(
            event_type=event_type,
            source="LOCAL_CLI",
            actor_account_id=None,
            target_account_id=owner_id,
        )
    )


def bootstrap_owner(connection: Connection) -> PendingOwnerSecret:
    """Create the only OWNER, 24h pending verifier and audit in the caller's transaction.

    The unique OWNER index is the final guard if another transaction races this one.
    Never print the secret here; after a failed commit it must never be delivered.
    """
    if connection.scalar(select(Account.id).where(Account.role == "OWNER")) is not None:
        raise ValueError("Owner account already exists")
    secret = generate_initial_secret()
    owner_id = connection.execute(
        insert(Account.__table__).values(role="OWNER").returning(Account.id)
    ).scalar_one()
    connection.execute(
        insert(AccountCredential.__table__).values(
            account_id=owner_id,
            initial_secret_digest=initial_secret_digest(secret),
            initial_secret_expires_at=func.now() + text("interval '24 hours'"),
        )
    )
    _record_owner_event(connection, owner_id, "OWNER_BOOTSTRAP_ISSUED")
    return PendingOwnerSecret(account_id=owner_id, secret=secret)


def reissue_pending_owner_secret(connection: Connection) -> PendingOwnerSecret:
    """Rotate an unactivated owner's one-time secret under a row lock and audit it.

    Lock ordering is Account then AccountCredential; later activation must use the
    same ordering. Reissue is forbidden after password setup or MFA enrollment.
    """
    owner = connection.execute(
        select(Account.id, Account.status)
        .where(Account.role == "OWNER")
        .with_for_update()
    ).one_or_none()
    if owner is None or owner.status != "ENABLED":
        raise ValueError("Pending owner setup is unavailable")
    credential = connection.execute(
        select(AccountCredential.password_hash, AccountCredential.initial_secret_consumed_at)
        .where(AccountCredential.account_id == owner.id)
        .with_for_update()
    ).one_or_none()
    if (
        credential is None
        or credential.password_hash is not None
        or credential.initial_secret_consumed_at is not None
        or connection.scalar(select(OwnerMFA.account_id).where(OwnerMFA.account_id == owner.id))
        is not None
    ):
        raise ValueError("Pending owner setup is unavailable")

    secret = generate_initial_secret()
    connection.execute(
        update(AccountCredential.__table__)
        .where(AccountCredential.account_id == owner.id)
        .values(
            initial_secret_digest=initial_secret_digest(secret),
            initial_secret_issued_at=func.now(),
            initial_secret_expires_at=func.now() + text("interval '24 hours'"),
        )
    )
    _record_owner_event(connection, owner.id, "OWNER_BOOTSTRAP_REISSUED")
    return PendingOwnerSecret(account_id=owner.id, secret=secret)
