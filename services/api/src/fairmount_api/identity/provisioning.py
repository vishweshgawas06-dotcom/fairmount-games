"""Owner-only member provisioning; shared by restricted operator adapters.

This slice lets the owner create agents and players; assignment to an agent
is a separate audited action in `account_admin`. D-10 also permits agents to
create only their own assigned players via `agent_provisioning`; this module
continues to require owner authority. Agents never create sub-agents.

Every call requires a live owner session whose MFA proof is no older than ten
minutes, then re-checks the caller's role under the same transaction. The
one-time secret is returned once, in memory, and only its digest is stored; it
expires after 24 hours and the account cannot authenticate until the member
consumes it with a permanent password. Nothing here logs, prints or audits the
secret itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import Connection, func, insert, select
from sqlalchemy.exc import IntegrityError

from fairmount_api.db.models import (
    Account,
    AccountCredential,
    PrivateIdentity,
    SecurityEvent,
)
from fairmount_api.identity.credentials import generate_initial_secret, initial_secret_digest
from fairmount_api.identity.identifiers import (
    canonical_agent_id,
    canonical_player_username,
    generate_agent_id,
)
from fairmount_api.identity.owner_step_up import require_recent_owner_mfa

INITIAL_SECRET_LIFETIME = timedelta(hours=24)
_AGENT_ID_ATTEMPTS = 5


class ProvisioningUnavailable(ValueError):
    """Generic denial: never reveal whether an ID exists or who the caller is."""


@dataclass(frozen=True)
class ProvisionedMember:
    """One freshly created member; the secret is returned once and never stored."""

    account_id: uuid.UUID
    login_id: str  # display form: uppercase Agent ID or lowercase username
    secret: str = field(repr=False)
    expires_at: datetime


def _require_owner(connection: Connection, raw_owner_token: object) -> uuid.UUID:
    if not isinstance(raw_owner_token, str):
        raise ProvisioningUnavailable("Provisioning unavailable")
    verified = require_recent_owner_mfa(connection, raw_owner_token)
    if verified is None or verified.role != "OWNER":
        raise ProvisioningUnavailable("Provisioning unavailable")
    # Re-read the row inside the transaction: a concurrent disablement wins.
    owner = connection.execute(
        select(Account.id, Account.status, Account.role)
        .where(Account.id == verified.account_id)
        .with_for_update()
    ).one_or_none()
    if owner is None or owner.role != "OWNER" or owner.status != "ENABLED":
        raise ProvisioningUnavailable("Provisioning unavailable")
    return owner.id


def _login_taken(connection: Connection, kind: str, canonical: str) -> bool:
    return (
        connection.scalar(
            select(PrivateIdentity.account_id).where(
                PrivateIdentity.login_kind == kind,
                PrivateIdentity.login_identifier == canonical,
            )
        )
        is not None
    )


def _insert_member(
    connection: Connection,
    actor_id: uuid.UUID,
    *,
    role: str,
    canonical: str,
    display: str,
    display_name: str | None = None,
    mobile_number: str | None = None,
) -> ProvisionedMember:
    """Insert account, private identity, pending credential and audit atomically."""
    account_id = connection.execute(
        insert(Account.__table__).values(role=role).returning(Account.id)
    ).scalar_one()
    connection.execute(
        insert(PrivateIdentity.__table__).values(
            account_id=account_id,
            login_kind=role,
            login_identifier=canonical,
            display_name=display_name,
            mobile_number=mobile_number,
        )
    )
    secret = generate_initial_secret()
    now = connection.scalar(select(func.clock_timestamp()))
    expires_at = now + INITIAL_SECRET_LIFETIME
    connection.execute(
        insert(AccountCredential.__table__).values(
            account_id=account_id,
            initial_secret_digest=initial_secret_digest(secret),
            initial_secret_issued_at=now,
            initial_secret_expires_at=expires_at,
        )
    )
    connection.execute(
        insert(SecurityEvent.__table__).values(
            event_type="INITIAL_CREDENTIAL_ISSUED",
            source="DASHBOARD",
            actor_account_id=actor_id,
            target_account_id=account_id,
        )
    )
    return ProvisionedMember(account_id, display, secret, expires_at)


def validate_profile(display_name: str, mobile_number: str) -> None:
    """Bound unverified contact text; retain exact input, never infer identity.

    Country-specific phone normalization/verification is not approved. Shared
    numbers are allowed. This is storage validation, not a verified phone check.
    """
    for value, limit in ((display_name, 160), (mobile_number, 32)):
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= limit
            or not value.isprintable()
            or not value.strip()
        ):
            raise ProvisioningUnavailable("Provisioning unavailable")
        try:
            value.encode("utf-8")
        except UnicodeError as exc:
            raise ProvisioningUnavailable("Provisioning unavailable") from exc


def _create_member(connection: Connection, actor_id: uuid.UUID, **fields) -> ProvisionedMember:
    """Contain uniqueness races so duplicate registration leaves no partial rows."""
    name, mobile = fields.get("display_name"), fields.get("mobile_number")
    if name is not None or mobile is not None:
        validate_profile(name, mobile)
    try:
        with connection.begin_nested():
            return _insert_member(connection, actor_id, **fields)
    except IntegrityError as exc:
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == (
            "uq_private_identities_login_namespace"
        ):
            raise ProvisioningUnavailable("Provisioning unavailable") from exc
        raise


def provision_agent(
    connection: Connection,
    raw_owner_token: str,
    *,
    agent_id: str | None = None,
    display_name: str | None = None,
    mobile_number: str | None = None,
) -> ProvisionedMember:
    """Create one AGENT with a fixed Agent ID and a 24-hour one-time secret.

    An explicit `agent_id` is validated with the same canonical rules as login;
    otherwise a random ID is generated and a collision re-rolls, so the caller
    never sees a partial account. Agents cannot call this to create sub-agents.
    """
    owner_id = _require_owner(connection, raw_owner_token)
    if agent_id is None:
        # Generated IDs are canonicalised like explicit ones: the DB stores the
        # lowercase form only, and display case is reconstructed here.
        candidates = [generate_agent_id().lower() for _ in range(_AGENT_ID_ATTEMPTS)]
    else:
        try:
            candidates = [canonical_agent_id(agent_id)]
        except ValueError as exc:
            raise ProvisioningUnavailable("Provisioning unavailable") from exc
    for canonical in candidates:
        if _login_taken(connection, "AGENT", canonical):
            continue
        return _create_member(
            connection,
            owner_id,
            role="AGENT",
            canonical=canonical,
            display=canonical.upper(),
            display_name=display_name,
            mobile_number=mobile_number,
        )
    raise ProvisioningUnavailable("Provisioning unavailable")  # ID space exhausted


def provision_player(
    connection: Connection,
    raw_owner_token: str,
    *,
    username: str,
    display_name: str | None = None,
    mobile_number: str | None = None,
) -> ProvisionedMember:
    """Create one PLAYER owned by the owner, unassigned until an audited assignment."""
    owner_id = _require_owner(connection, raw_owner_token)
    try:
        canonical = canonical_player_username(username)
    except ValueError as exc:
        raise ProvisioningUnavailable("Provisioning unavailable") from exc
    if _login_taken(connection, "PLAYER", canonical):
        raise ProvisioningUnavailable("Provisioning unavailable")
    return _create_member(
        connection,
        owner_id,
        role="PLAYER",
        canonical=canonical,
        display=canonical,
        display_name=display_name,
        mobile_number=mobile_number,
    )
