"""Internal owner-issued points and conserved owner↔member transfers.

Call inside a transaction, then commit before reporting success. No HTTP route exists.
The request edge still needs throttling/failure audit, cookie/CSRF and step-up UX.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, insert, select

from fairmount_api.db.models import (
    Account,
    AccountWallet,
    PointLedgerEntry,
    PointOperation,
)
from fairmount_api.identity.owner_step_up import require_recent_owner_mfa

_MAX_POINTS = 2**63 - 1


class PointActionUnavailable(ValueError):
    """Safe, generic rejection: no caller-visible balance or account discovery."""


class PointActionConflict(PointActionUnavailable):
    """Idempotency key reused with different action parameters."""


@dataclass(frozen=True)
class PointActionResult:
    operation_id: uuid.UUID
    replayed: bool


def _validated(amount: int, reason: str, idempotency_key: str) -> tuple[int, str, str]:
    if type(amount) is not int or not 1 <= amount <= _MAX_POINTS:
        raise PointActionUnavailable("Point action unavailable")
    if not isinstance(reason, str) or not 0 < len(reason.strip()) <= 500:
        raise PointActionUnavailable("Point action unavailable")
    if not isinstance(idempotency_key, str) or not 0 < len(idempotency_key) <= 128:
        raise PointActionUnavailable("Point action unavailable")
    return amount, reason.strip(), idempotency_key


def _perform(
    connection: Connection,
    owner: uuid.UUID,
    *,
    kind: str,
    source: uuid.UUID | None,
    target: uuid.UUID,
    amount: int,
    reason: str,
    idempotency_key: str,
) -> PointActionResult:
    amount, reason, idempotency_key = _validated(amount, reason, idempotency_key)
    if not isinstance(target, uuid.UUID) or (
        source is not None and not isinstance(source, uuid.UUID)
    ):
        raise PointActionUnavailable("Point action unavailable")
    if kind == "OWNER_ISSUE":
        if source is not None or target != owner:
            raise PointActionUnavailable("Point action unavailable")
    elif kind == "OWNER_TRANSFER":
        if source is None or source == target or owner not in (source, target):
            raise PointActionUnavailable("Point action unavailable")
    else:
        raise PointActionUnavailable("Point action unavailable")

    fingerprint = hashlib.sha256(
        json.dumps(
            (kind, str(owner), str(source) if source else None, str(target), amount, reason),
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    # The owner Account lock from require_recent_owner_mfa serializes requests by
    # this sole actor, including competing uses of the same idempotency key.
    previous = connection.execute(
        select(PointOperation.id, PointOperation.request_fingerprint).where(
            PointOperation.actor_account_id == owner,
            PointOperation.idempotency_key == idempotency_key,
        )
    ).one_or_none()
    if previous is not None:
        if previous.request_fingerprint != fingerprint:
            raise PointActionConflict("Point action unavailable")
        return PointActionResult(previous.id, replayed=True)

    if kind == "OWNER_TRANSFER":
        member = target if source == owner else source
        account = connection.execute(
            select(Account.role, Account.status).where(Account.id == member).with_for_update()
        ).one_or_none()
        if (
            account is None
            or account.status != "ENABLED"
            or account.role not in ("AGENT", "PLAYER")
        ):
            raise PointActionUnavailable("Point action unavailable")

    wallets = {}
    for account_id in sorted({owner, target, *([source] if source is not None else [])}):
        wallet = connection.execute(
            select(AccountWallet.account_id, AccountWallet.balance)
            .where(AccountWallet.account_id == account_id)
            .with_for_update()
        ).one_or_none()
        if wallet is None:
            raise PointActionUnavailable("Point action unavailable")
        wallets[account_id] = wallet.balance
    if source is not None and wallets[source] < amount:
        raise PointActionUnavailable("Point action unavailable")
    if wallets[target] > _MAX_POINTS - amount:
        raise PointActionUnavailable("Point action unavailable")
    operation_id = connection.execute(
        insert(PointOperation.__table__)
        .values(
            kind=kind,
            actor_account_id=owner,
            actor_role="OWNER",
            source_wallet_id=source,
            target_wallet_id=target,
            amount=amount,
            reason=reason,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
        .returning(PointOperation.id)
    ).scalar_one()
    if source is not None:
        connection.execute(
            insert(PointLedgerEntry.__table__).values(
                operation_id=operation_id, wallet_account_id=source, delta=-amount
            )
        )
    connection.execute(
        insert(PointLedgerEntry.__table__).values(
            operation_id=operation_id, wallet_account_id=target, delta=amount
        )
    )
    return PointActionResult(operation_id, replayed=False)


def issue_owner_points(
    connection: Connection,
    raw_owner_token: str,
    *,
    amount: int,
    reason: str,
    idempotency_key: str,
) -> PointActionResult:
    """Owner-only creation of points in the owner wallet, never a target wallet."""
    # The actor is resolved and verified by the shared implementation, not
    # accepted as a caller-supplied owner ID.
    verified = require_recent_owner_mfa(connection, raw_owner_token)
    if verified is None:
        raise PointActionUnavailable("Point action unavailable")
    return _perform(
        connection,
        verified.account_id,
        kind="OWNER_ISSUE",
        source=None,
        target=verified.account_id,
        amount=amount,
        reason=reason,
        idempotency_key=idempotency_key,
    )


def transfer_owner_points(
    connection: Connection,
    raw_owner_token: str,
    *,
    member_account_id: uuid.UUID,
    amount: int,
    to_member: bool,
    reason: str,
    idempotency_key: str,
) -> PointActionResult:
    """Fund an enabled agent/player from owner, or return their full amount."""
    if type(to_member) is not bool or not isinstance(member_account_id, uuid.UUID):
        raise PointActionUnavailable("Point action unavailable")
    verified = require_recent_owner_mfa(connection, raw_owner_token)
    if verified is None:
        raise PointActionUnavailable("Point action unavailable")
    return _perform(
        connection,
        verified.account_id,
        kind="OWNER_TRANSFER",
        source=verified.account_id if to_member else member_account_id,
        target=member_account_id if to_member else verified.account_id,
        amount=amount,
        reason=reason,
        idempotency_key=idempotency_key,
    )
