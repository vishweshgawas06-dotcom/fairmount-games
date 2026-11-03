"""DB-serialized attempt windows for gameplay writes; not an HTTP endpoint.

A player can afford a handful of bets per minute; a script can afford thousands.
Every gameplay write that passes the request envelope therefore takes two
pseudonymous buckets — one for the presented session, one for the transport
source — before admission runs. Keys are keyed HMACs, so the table stores no
token, account, address or bet content.

The guard runs the admission callback inside a SAVEPOINT so an expected denial
does not release the bucket locks. Counters deliberately count *attempts*, not
failures: a rejected flood costs the same database work as an accepted one.
The caller must commit the outer transaction whether the outcome is allowed,
denied or throttled.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import Connection, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from fairmount_api.db.models import GameplayWriteBucket
from fairmount_api.identity.session_validation import session_token_digest

WINDOW = timedelta(minutes=1)
SESSION_LIMIT = 20
SOURCE_LIMIT = 120


@dataclass(frozen=True)
class WriteLimitOutcome:
    """Allowed, denied or throttled; the callback value never appears in ``repr``."""

    allowed: bool
    throttled: bool
    retry_after: int
    value: object | None = field(default=None, repr=False)
    denial: type[Exception] | None = None


@dataclass(frozen=True)
class _Window:
    used: int
    expired: bool
    reopens_in: int


def _source_digest(source_ip: str, pepper: bytes) -> str:
    if not isinstance(source_ip, str) or len(source_ip) > 45:
        raise ValueError("A verified transport IP is required")
    try:
        address = str(ipaddress.ip_address(source_ip))
    except ValueError as exc:
        raise ValueError("A verified transport IP is required") from exc
    return hmac.new(pepper, f"source\0{address}".encode(), hashlib.sha256).hexdigest()


def _session_digest(raw_token: object, pepper: bytes) -> str:
    """Key by the token digest, never the token: one unrevoked session per account."""
    digest = session_token_digest(raw_token) if isinstance(raw_token, str) else None
    if digest is None:
        raise ValueError("A well-shaped session token is required")
    return hmac.new(pepper, f"session\0{digest}".encode("ascii"), hashlib.sha256).hexdigest()


def _windows(connection: Connection, limits: Mapping[str, int]) -> dict[str, _Window]:
    """Lock both buckets in sorted order (no deadlock) and read their windows."""
    for key in sorted(limits):
        connection.execute(
            pg_insert(GameplayWriteBucket.__table__)
            .values(key_digest=key, window_started_at=func.clock_timestamp(), attempts=0)
            .on_conflict_do_nothing(index_elements=["key_digest"])
        )
    rows = {
        key: connection.execute(
            select(GameplayWriteBucket.window_started_at, GameplayWriteBucket.attempts)
            .where(GameplayWriteBucket.key_digest == key)
            .with_for_update()
        ).one()
        for key in sorted(limits)
    }
    now = connection.scalar(select(func.clock_timestamp()))
    windows = {}
    for key, row in rows.items():
        expired = now >= row.window_started_at + WINDOW
        reopens_in = max(1, int((row.window_started_at + WINDOW - now).total_seconds()) + 1)
        windows[key] = _Window(
            used=0 if expired else row.attempts, expired=expired, reopens_in=reopens_in
        )
    return windows


def _spend(connection: Connection, windows: Mapping[str, _Window]) -> None:
    """Count exactly one attempt per key, restarting a window that has expired."""
    for key, window in windows.items():
        if window.expired:
            values = {"window_started_at": func.clock_timestamp(), "attempts": 1}
        else:
            values = {"attempts": GameplayWriteBucket.attempts + 1}
        connection.execute(
            update(GameplayWriteBucket.__table__)
            .where(GameplayWriteBucket.key_digest == key)
            .values(**values)
        )


def guard_gameplay_write(
    connection: Connection,
    raw_token: str,
    *,
    source_ip: str,
    pepper: bytes,
    write: Callable[[Connection], object],
    denied_by: tuple[type[Exception], ...],
) -> WriteLimitOutcome:
    """Serialise session/source windows, then run ``write`` in a SAVEPOINT.

    Expected denials from ``denied_by`` become ``allowed=False`` after their
    side effects roll back to the savepoint; the attempt still counts.
    Unexpected exceptions propagate, so a database fault is never reported as a
    throttle or a normal rejection.
    """
    if type(pepper) is not bytes or len(pepper) < 32:
        raise ValueError("A distinct deployment-owned secret is required")
    if (
        not callable(write)
        or not denied_by
        or not all(isinstance(cls, type) and issubclass(cls, Exception) for cls in denied_by)
    ):
        raise ValueError("A trusted write callback and denial types are required")
    limits = {
        _session_digest(raw_token, pepper): SESSION_LIMIT,
        _source_digest(source_ip, pepper): SOURCE_LIMIT,
    }
    windows = _windows(connection, limits)
    exhausted = [w.reopens_in for key, w in windows.items() if w.used >= limits[key]]
    if exhausted:
        return WriteLimitOutcome(allowed=False, throttled=True, retry_after=min(exhausted))
    _spend(connection, windows)
    try:
        with connection.begin_nested():
            value = write(connection)
    except denied_by as denial:
        return WriteLimitOutcome(
            allowed=False, throttled=False, retry_after=0, denial=type(denial)
        )
    return WriteLimitOutcome(allowed=True, throttled=False, retry_after=0, value=value)
