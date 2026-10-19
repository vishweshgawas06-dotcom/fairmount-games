"""Internal atomic owner MFA proof. No session, route, or login permission is issued.

Caller owns the transaction and must already have verified the owner's password for
login, or a currently valid owner session for step-up. Never expose this function
without rate limits, failure accounting and authorization at the request boundary.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Connection, func, insert, select, update

from fairmount_api.db.models import (
    Account,
    AccountCredential,
    OwnerMFA,
    OwnerRecoveryCode,
    SecurityEvent,
)
from fairmount_api.identity.mfa import (
    RECOVERY_ALPHABET,
    matched_totp_step,
    recovery_code_digest,
    verify_recovery_code,
)
from fairmount_api.identity.mfa_encryption import EncryptedTOTPSecret, decrypt_totp_secret
from fairmount_api.identity.mfa_keys import MFAKeyring


class OwnerMFAProofUnavailable(ValueError):
    """Fail closed without revealing the factor state or code validity."""


def verify_owner_mfa(
    connection: Connection,
    owner_id: uuid.UUID,
    factor_kind: str,
    code: str,
    keyring: MFAKeyring,
) -> datetime:
    """Return DB verification time only after atomic proof and append-only audit.

    Lock order Account -> AccountCredential -> OwnerMFA -> recovery row. Rollback
    undoes step/code consumption and audit. TOTP uses monotonically increasing
    30-second steps; recovery codes have one null-to-consumed transition.
    """
    if not isinstance(owner_id, uuid.UUID) or factor_kind not in ("totp", "recovery"):
        raise OwnerMFAProofUnavailable("Owner MFA proof unavailable")
    account = connection.execute(
        select(Account.role, Account.status).where(Account.id == owner_id).with_for_update()
    ).one_or_none()
    if account is None or account.role != "OWNER" or account.status != "ENABLED":
        raise OwnerMFAProofUnavailable("Owner MFA proof unavailable")
    credential = connection.execute(
        select(AccountCredential.password_hash)
        .where(AccountCredential.account_id == owner_id)
        .with_for_update()
    ).one_or_none()
    if credential is None or credential.password_hash is None:
        raise OwnerMFAProofUnavailable("Owner MFA proof unavailable")
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
    if factor is None or factor.confirmed_at is None:
        raise OwnerMFAProofUnavailable("Owner MFA proof unavailable")
    now = connection.scalar(select(func.clock_timestamp()))
    if now < factor.confirmed_at:
        raise OwnerMFAProofUnavailable("Owner MFA proof unavailable")
    if factor_kind == "totp":
        try:
            secret = decrypt_totp_secret(
                EncryptedTOTPSecret(
                    key_version=factor.key_version,
                    nonce=factor.nonce,
                    ciphertext=factor.ciphertext,
                ),
                account_id=owner_id,
                key=keyring.key_for(factor.key_version),
            )
        except ValueError as exc:
            raise OwnerMFAProofUnavailable("Owner MFA proof unavailable") from exc
        step = matched_totp_step(secret, code, int(now.timestamp()))
        if step is None or (
            factor.last_accepted_step is not None and step <= factor.last_accepted_step
        ):
            raise OwnerMFAProofUnavailable("Owner MFA proof unavailable")
        connection.execute(
            update(OwnerMFA.__table__)
            .where(OwnerMFA.account_id == owner_id)
            .values(last_accepted_step=step)
        )
    else:
        if not isinstance(code, str) or len(code) > 19 or not code.isascii():
            raise OwnerMFAProofUnavailable("Owner MFA proof unavailable")
        canonical = code.upper().replace("-", "")
        if len(canonical) != 16 or any(char not in RECOVERY_ALPHABET for char in canonical):
            raise OwnerMFAProofUnavailable("Owner MFA proof unavailable")
        digest = recovery_code_digest(canonical)
        recovery = connection.execute(
            select(OwnerRecoveryCode.id, OwnerRecoveryCode.digest, OwnerRecoveryCode.issued_at)
            .where(
                OwnerRecoveryCode.owner_account_id == owner_id,
                OwnerRecoveryCode.digest == digest,
                OwnerRecoveryCode.consumed_at.is_(None),
            )
            .with_for_update()
        ).one_or_none()
        if (
            recovery is None
            or now < recovery.issued_at
            or not verify_recovery_code(code, recovery.digest)
        ):
            raise OwnerMFAProofUnavailable("Owner MFA proof unavailable")
        connection.execute(
            update(OwnerRecoveryCode.__table__)
            .where(OwnerRecoveryCode.id == recovery.id, OwnerRecoveryCode.consumed_at.is_(None))
            .values(consumed_at=now)
        )
    connection.execute(
        insert(SecurityEvent.__table__).values(
            event_type="OWNER_MFA_VERIFIED",
            source="SELF_SERVICE",
            actor_account_id=owner_id,
            target_account_id=owner_id,
            occurred_at=now,
        )
    )
    return now
