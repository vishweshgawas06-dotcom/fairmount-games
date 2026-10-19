"""Internal owner MFA enrollment transactions; no public enrollment or session.

Callers MUST commit before handing the seed or recovery codes to the owner. Do not
expose these functions without protected local delivery, rate limits and audit review.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, func, insert, select, update

from fairmount_api.db.models import (
    Account,
    AccountCredential,
    OwnerMFA,
    OwnerRecoveryCode,
    SecurityEvent,
)
from fairmount_api.identity.mfa import (
    generate_recovery_codes,
    generate_totp_secret,
    matched_totp_step,
    recovery_code_digest,
)
from fairmount_api.identity.mfa_encryption import (
    EncryptedTOTPSecret,
    decrypt_totp_secret,
    encrypt_totp_secret,
)
from fairmount_api.identity.mfa_keys import MFAKeyring


class OwnerMFAUnavailable(ValueError):
    """No enrollment or verification path is currently valid."""


@dataclass(frozen=True)
class PendingOwnerMFA:
    account_id: uuid.UUID
    secret: str = field(repr=False)


@dataclass(frozen=True)
class ConfirmedOwnerMFA:
    account_id: uuid.UUID
    recovery_codes: tuple[str, ...] = field(repr=False)


def _eligible_owner(connection: Connection) -> uuid.UUID:
    # Lock ordering remains Account -> AccountCredential -> OwnerMFA.
    owner = connection.execute(
        select(Account.id, Account.status).where(Account.role == "OWNER").with_for_update()
    ).one_or_none()
    if owner is None or owner.status != "ENABLED":
        raise OwnerMFAUnavailable("Owner MFA enrollment unavailable")
    credential = connection.execute(
        select(AccountCredential.password_hash)
        .where(AccountCredential.account_id == owner.id)
        .with_for_update()
    ).one_or_none()
    if credential is None or credential.password_hash is None:
        raise OwnerMFAUnavailable("Owner MFA enrollment unavailable")
    return owner.id


def begin_owner_mfa_enrollment(connection: Connection, keyring: MFAKeyring) -> PendingOwnerMFA:
    """Store an unconfirmed encrypted factor; return seed only after caller commits."""
    owner_id = _eligible_owner(connection)
    if connection.scalar(select(OwnerMFA.account_id).where(OwnerMFA.account_id == owner_id)):
        raise OwnerMFAUnavailable("Owner MFA enrollment unavailable")
    version, key = keyring.active_key()
    secret = generate_totp_secret()
    encrypted = encrypt_totp_secret(secret, account_id=owner_id, key=key, key_version=version)
    connection.execute(
        insert(OwnerMFA.__table__).values(
            account_id=owner_id,
            key_version=encrypted.key_version,
            nonce=encrypted.nonce,
            ciphertext=encrypted.ciphertext,
        )
    )
    return PendingOwnerMFA(account_id=owner_id, secret=secret)


def confirm_owner_mfa_enrollment(
    connection: Connection, code: str, keyring: MFAKeyring
) -> ConfirmedOwnerMFA:
    """Validate a live code, store ten digests and audit in one caller transaction."""
    owner_id = _eligible_owner(connection)
    factor = connection.execute(
        select(
            OwnerMFA.key_version,
            OwnerMFA.nonce,
            OwnerMFA.ciphertext,
            OwnerMFA.confirmed_at,
            OwnerMFA.last_accepted_step,
        )
        .where(OwnerMFA.account_id == owner_id)
        .with_for_update()
    ).one_or_none()
    if factor is None or factor.confirmed_at is not None or factor.last_accepted_step is not None:
        raise OwnerMFAUnavailable("Owner MFA enrollment unavailable")
    if connection.scalar(
        select(OwnerRecoveryCode.id).where(OwnerRecoveryCode.owner_account_id == owner_id).limit(1)
    ):
        raise OwnerMFAUnavailable("Owner MFA enrollment unavailable")
    encrypted = EncryptedTOTPSecret(
        key_version=factor.key_version, nonce=factor.nonce, ciphertext=factor.ciphertext
    )
    secret = decrypt_totp_secret(
        encrypted, account_id=owner_id, key=keyring.key_for(factor.key_version)
    )
    now = connection.scalar(select(func.clock_timestamp()))
    step = matched_totp_step(secret, code, int(now.timestamp()))
    if step is None:
        raise OwnerMFAUnavailable("Owner MFA enrollment unavailable")
    recovery_codes = generate_recovery_codes()
    for recovery_code in recovery_codes:
        connection.execute(
            insert(OwnerRecoveryCode.__table__).values(
                owner_account_id=owner_id,
                digest=recovery_code_digest(recovery_code),
            )
        )
    connection.execute(
        update(OwnerMFA.__table__)
        .where(OwnerMFA.account_id == owner_id)
        .values(confirmed_at=now, last_accepted_step=step)
    )
    connection.execute(
        insert(SecurityEvent.__table__).values(
            event_type="OWNER_MFA_ENROLLED",
            source="SELF_SERVICE",
            actor_account_id=owner_id,
            target_account_id=owner_id,
        )
    )
    return ConfirmedOwnerMFA(account_id=owner_id, recovery_codes=recovery_codes)
