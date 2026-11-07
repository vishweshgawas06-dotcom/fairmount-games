"""Transaction-scoped member activation and owner-only pending-secret reissue.

Never grants a session or changes an active password. The caller must commit
before reporting activation or handing off a new one-time secret.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Connection, func, insert, select, update

from fairmount_api.db.models import Account, AccountCredential, PrivateIdentity, SecurityEvent
from fairmount_api.identity.credentials import (
    generate_initial_secret,
    hash_password,
    initial_secret_digest,
    verify_initial_secret,
)
from fairmount_api.identity.identifiers import canonical_agent_id, canonical_player_username
from fairmount_api.identity.provisioning import (
    INITIAL_SECRET_LIFETIME,
    ProvisionedMember,
    _require_owner,
)


class MemberActivationUnavailable(ValueError):
    """Generic denial; neither credentials nor account existence are disclosed."""


def _pending_credential(connection: Connection, account_id: uuid.UUID):
    credential = connection.execute(
        select(AccountCredential)
        .where(AccountCredential.account_id == account_id)
        .with_for_update()
    ).one_or_none()
    if (
        credential is None
        or credential.password_hash is not None
        or credential.initial_secret_consumed_at is not None
        or credential.initial_secret_digest is None
        or credential.initial_secret_expires_at is None
    ):
        raise MemberActivationUnavailable("Member activation unavailable")
    return credential


def activate_member(
    connection: Connection, *, role: str, identifier: str, secret: str, new_password: str
) -> uuid.UUID:
    """Consume the role-bound 24h setup secret once and set a permanent password.

    Account -> Credential locks serialize activation, reissue and disablement.
    Expiry is checked before AND after Argon2 hashing against PostgreSQL time.
    Login still requires the ordinary guarded role-specific login endpoint.
    """
    try:
        if role == "AGENT":
            canonical = canonical_agent_id(identifier)
        elif role == "PLAYER":
            canonical = canonical_player_username(identifier)
        else:
            raise ValueError("Unsupported role")
    except ValueError as exc:
        raise MemberActivationUnavailable("Member activation unavailable") from exc
    account_id = connection.scalar(
        select(PrivateIdentity.account_id).where(
            PrivateIdentity.login_kind == role, PrivateIdentity.login_identifier == canonical
        )
    )
    if account_id is None:
        raise MemberActivationUnavailable("Member activation unavailable")
    account = connection.execute(
        select(Account.role, Account.status).where(Account.id == account_id).with_for_update()
    ).one_or_none()
    if account is None or account.role != role or account.status != "ENABLED":
        raise MemberActivationUnavailable("Member activation unavailable")
    credential = _pending_credential(connection, account_id)
    try:
        valid_secret = verify_initial_secret(secret, credential.initial_secret_digest)
    except UnicodeError as exc:
        raise MemberActivationUnavailable("Member activation unavailable") from exc
    if (
        not valid_secret
        or connection.scalar(select(func.clock_timestamp())) >= credential.initial_secret_expires_at
    ):
        raise MemberActivationUnavailable("Member activation unavailable")
    try:
        password_hash = hash_password(new_password)
    except ValueError as exc:
        raise MemberActivationUnavailable("Member activation unavailable") from exc
    now = connection.scalar(select(func.clock_timestamp()))
    if now >= credential.initial_secret_expires_at:
        raise MemberActivationUnavailable("Member activation unavailable")
    connection.execute(
        update(AccountCredential.__table__)
        .where(AccountCredential.account_id == account_id)
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
            actor_account_id=account_id,
            target_account_id=account_id,
        )
    )
    return account_id


def reissue_pending_member_secret(
    connection: Connection, raw_owner_token: str, *, account_id: uuid.UUID
) -> ProvisionedMember:
    """Fresh-MFA owner rotates a pending member secret; never resets an active password.

    Can recover a lost provisioning response, including an expired pending
    secret. Rejects owner/disabled/missing/active targets. The previous secret
    immediately stops working; audit, rotation and HTTP receipt commit together.
    """
    owner_id = _require_owner(connection, raw_owner_token)
    if not isinstance(account_id, uuid.UUID):
        raise MemberActivationUnavailable("Member activation unavailable")
    account = connection.execute(
        select(Account.role, Account.status).where(Account.id == account_id).with_for_update()
    ).one_or_none()
    if account is None or account.role not in ("AGENT", "PLAYER") or account.status != "ENABLED":
        raise MemberActivationUnavailable("Member activation unavailable")
    _pending_credential(connection, account_id)
    login = connection.scalar(
        select(PrivateIdentity.login_identifier).where(
            PrivateIdentity.account_id == account_id, PrivateIdentity.login_kind == account.role
        )
    )
    if login is None:
        raise MemberActivationUnavailable("Member activation unavailable")
    secret = generate_initial_secret()
    now = connection.scalar(select(func.clock_timestamp()))
    expiry = now + INITIAL_SECRET_LIFETIME
    connection.execute(
        update(AccountCredential.__table__)
        .where(AccountCredential.account_id == account_id)
        .values(
            initial_secret_digest=initial_secret_digest(secret),
            initial_secret_issued_at=now,
            initial_secret_expires_at=expiry,
        )
    )
    connection.execute(
        insert(SecurityEvent.__table__).values(
            event_type="INITIAL_CREDENTIAL_REISSUED",
            source="DASHBOARD",
            actor_account_id=owner_id,
            target_account_id=account_id,
        )
    )
    return ProvisionedMember(
        account_id, login.upper() if account.role == "AGENT" else login, secret, expiry
    )
