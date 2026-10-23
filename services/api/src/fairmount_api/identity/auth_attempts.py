"""Private PostgreSQL authentication-attempt guard; not an HTTP endpoint.

The caller supplies a restricted deployment secret (not the MFA encryption key),
a transport-verified client IP (never an untrusted forwarded header), a trusted
authentication callback and its expected denial exceptions. Commit the outer
transaction before returning a successful token or reporting a denial. Raw
identifiers, addresses, passwords, codes and tokens are never persisted here.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import Connection, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from fairmount_api.db.models import AuthAttemptBucket, AuthFailureEvent

WINDOW = timedelta(minutes=15)
SUBJECT_LIMIT = 5
SOURCE_LIMIT = 30
_SURFACES = frozenset(("OWNER_LOGIN", "MEMBER_LOGIN", "OWNER_MFA"))


@dataclass(frozen=True)
class AuthAttemptOutcome:
    allowed: bool
    throttled: bool
    value: object | None = field(default=None, repr=False)


def _digests(surface: str, identifier: str, source_ip: str, pepper: bytes) -> tuple[str, str]:
    if surface not in _SURFACES or not isinstance(identifier, str):
        raise ValueError("Invalid authentication context")
    if type(pepper) is not bytes or len(pepper) < 32:
        raise ValueError("A distinct deployment-owned authentication secret is required")
    if not isinstance(source_ip, str) or len(source_ip) > 45:
        raise ValueError("A verified transport IP is required")
    try:
        ip = str(ipaddress.ip_address(source_ip))
    except ValueError as exc:
        raise ValueError("A verified transport IP is required") from exc
    # Group malformed identifiers under one rate-limit key without ever saving
    # the raw input. Role is part of the subject domain; source spans roles.
    canonical = identifier.strip().casefold() if len(identifier) <= 128 else "<invalid>"
    if not 1 <= len(canonical) <= 128:
        canonical = "<invalid>"
    subject = hmac.new(pepper, f"subject\0{surface}\0{canonical}".encode(), hashlib.sha256)
    source = hmac.new(pepper, f"source\0{ip}".encode(), hashlib.sha256)
    return subject.hexdigest(), source.hexdigest()


def guarded_authentication(
    connection: Connection,
    *,
    surface: str,
    identifier: str,
    source_ip: str,
    pepper: bytes,
    authenticate: Callable[[Connection], object],
    denied_by: tuple[type[Exception], ...],
) -> AuthAttemptOutcome:
    """Serialize subject/source windows and journal failed/blocked attempts.

    The callback runs in a SAVEPOINT: an expected denial can roll back proof or
    session side effects without releasing the two bucket locks, then a generic
    pseudonymous failure can be recorded in the *committed outer transaction*.
    Unexpected exceptions propagate and roll everything back; never convert a
    database outage to an 'incorrect password' response. The caller must treat
    both denied and throttled outcomes generically at the request edge.
    """
    if (
        not callable(authenticate)
        or not denied_by
        or not all(isinstance(cls, type) and issubclass(cls, Exception) for cls in denied_by)
    ):
        raise ValueError("A trusted authentication callback and denial types are required")
    subject, source = _digests(surface, identifier, source_ip, pepper)
    # Deterministic lock order prevents deadlocks when requests share one key.
    keys = sorted((subject, source))
    for key in keys:
        connection.execute(
            pg_insert(AuthAttemptBucket.__table__)
            .values(key_digest=key, window_started_at=func.clock_timestamp(), failures=0)
            .on_conflict_do_nothing(index_elements=["key_digest"])
        )
    rows = {}
    for key in keys:
        rows[key] = connection.execute(
            select(AuthAttemptBucket.window_started_at, AuthAttemptBucket.failures)
            .where(AuthAttemptBucket.key_digest == key)
            .with_for_update()
        ).one()
    now = connection.scalar(select(func.clock_timestamp()))

    def active_failures(key: str) -> int:
        row = rows[key]
        return row.failures if now < row.window_started_at + WINDOW else 0

    blocked = active_failures(subject) >= SUBJECT_LIMIT or active_failures(source) >= SOURCE_LIMIT
    if blocked:
        connection.execute(
            insert(AuthFailureEvent.__table__).values(
                subject_digest=subject,
                source_digest=source,
                surface=surface,
                outcome="THROTTLED",
                occurred_at=now,
            )
        )
        return AuthAttemptOutcome(allowed=False, throttled=True)
    try:
        with connection.begin_nested():
            value = authenticate(connection)
    except denied_by:
        for key in keys:
            row = rows[key]
            restart = now >= row.window_started_at + WINDOW
            connection.execute(
                update(AuthAttemptBucket.__table__)
                .where(AuthAttemptBucket.key_digest == key)
                .values(
                    window_started_at=now if restart else row.window_started_at,
                    failures=1 if restart else row.failures + 1,
                )
            )
        connection.execute(
            insert(AuthFailureEvent.__table__).values(
                subject_digest=subject,
                source_digest=source,
                surface=surface,
                outcome="FAILED",
                occurred_at=now,
            )
        )
        return AuthAttemptOutcome(allowed=False, throttled=False)
    # A valid login clears only the subject bucket: an attacker cannot use one
    # known-good account to reset the shared source quota after many bad IDs.
    connection.execute(
        update(AuthAttemptBucket.__table__)
        .where(AuthAttemptBucket.key_digest == subject)
        .values(window_started_at=now, failures=0)
    )
    return AuthAttemptOutcome(allowed=True, throttled=False, value=value)
