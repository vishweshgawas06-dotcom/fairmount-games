"""Private replace-snapshot SSE: every poll reauthorizes, no cached replay.

This incremental feed is not a durable event bus. Each connection starts at one,
receives current state, and closes after a bounded lifetime. A denied scope or DB
failure terminates it without reusing a previously authorized private payload.
"""

from __future__ import annotations

import asyncio
import json
import math
import threading
import uuid
from collections.abc import AsyncIterator, Callable

from sqlalchemy import Connection, func, select
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from fairmount_api.db.models import RouletteBet
from fairmount_api.identity.session_validation import resolve_session
from fairmount_api.readiness import _configured_engine, schema_ready
from fairmount_api.resource_reads import ResourceUnavailable, _authorize_target, _wallet_balance

POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 15.0
MAX_SECONDS = 60.0
MAX_STREAMS = 32
MAX_PER_SESSION = 2


class PrivateBackendUnavailable(RuntimeError):
    """No usable schema/database; not a session or scope assertion."""


class PrivateCapacityUnavailable(ValueError):
    """Bounded process-local stream capacity; not a production capacity target."""


class Capacity:
    def __init__(self, total=MAX_STREAMS, per_session=MAX_PER_SESSION):
        self.total = total
        self.per_session = per_session
        self.sessions: dict[str, int] = {}
        self._lock = threading.Lock()

    def enter(self, digest: str):
        with self._lock:
            if sum(self.sessions.values()) >= self.total or (
                self.sessions.get(digest, 0) >= self.per_session
            ):
                raise PrivateCapacityUnavailable("Stream unavailable")
            self.sessions[digest] = self.sessions.get(digest, 0) + 1

    def leave(self, digest: str):
        with self._lock:
            count = self.sessions.get(digest, 0)
            if count <= 1:
                self.sessions.pop(digest, None)
            else:
                self.sessions[digest] = count - 1


capacity = Capacity()


def project_private_snapshot(connection: Connection, token: str, target: uuid.UUID | None) -> dict:
    """Reauthorize one poll. Read locks last only through this short transaction."""
    actor = resolve_session(connection, token, touch_idle=False)
    if actor is None:
        raise ResourceUnavailable("Resource unavailable")
    account_id = actor.account_id if target is None else target
    _authorize_target(connection, actor, account_id, player_only=target is not None)
    wallet = _wallet_balance(connection, account_id)
    payload = {
        "account_id": str(wallet.account_id),
        "balance": str(wallet.balance),
        "observed_at": connection.scalar(select(func.clock_timestamp())).isoformat(),
    }
    if target is None:
        payload["role"] = actor.role
        if actor.role == "PLAYER":
            rows = connection.execute(
                select(
                    RouletteBet.id,
                    RouletteBet.round_id,
                    RouletteBet.selection_key,
                    RouletteBet.accepted_stake,
                    RouletteBet.accepted_at,
                )
                .where(RouletteBet.player_account_id == actor.account_id)
                .order_by(RouletteBet.accepted_at.desc(), RouletteBet.id.desc())
                .limit(100)
            ).all()
            payload["recent_accepted_bets"] = [
                {
                    "bet_id": str(row.id),
                    "round_id": str(row.round_id),
                    "selection_key": row.selection_key,
                    "stake": str(row.accepted_stake),
                    "accepted_at": row.accepted_at.isoformat(),
                }
                for row in rows
            ]
    return payload


def load_snapshot(token: str, target: uuid.UUID | None) -> dict:
    engine = _configured_engine()
    if engine is None:
        raise PrivateBackendUnavailable("Resource unavailable")
    with engine.begin() as connection:
        # A held wallet/account lock must not pin an SSE coroutine/DB slot
        # indefinitely. These are local to this read transaction, not the engine.
        connection.exec_driver_sql("SET LOCAL statement_timeout = '2s'")
        connection.exec_driver_sql("SET LOCAL lock_timeout = '500ms'")
        if not schema_ready(connection):
            raise PrivateBackendUnavailable("Resource unavailable")
        return project_private_snapshot(connection, token, target)


def _frame(event: str, payload: dict, identifier: int | None = None) -> str:
    prefix = f"id: {identifier}\n" if identifier is not None else ""
    return f"{prefix}event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


async def events(
    read: Callable[[], dict], *, poll_seconds=None, heartbeat_seconds=None, max_seconds=None
) -> AsyncIterator[str]:
    poll = POLL_SECONDS if poll_seconds is None else poll_seconds
    heartbeat = HEARTBEAT_SECONDS if heartbeat_seconds is None else heartbeat_seconds
    maximum = MAX_SECONDS if max_seconds is None else max_seconds
    for value in (poll, heartbeat, maximum):
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or (not math.isfinite(value) or value <= 0)
        ):
            raise ValueError("Invalid stream timing")
    if max(poll, heartbeat) > maximum:
        raise ValueError("Invalid stream timing")
    loop = asyncio.get_running_loop()
    deadline, next_heartbeat = loop.time() + maximum, loop.time() + heartbeat
    fingerprint, sequence = None, 0
    yield "retry: 3000\n\n"
    while loop.time() < deadline:
        try:
            payload = await run_in_threadpool(read)
        except (ResourceUnavailable, PrivateBackendUnavailable, SQLAlchemyError):
            yield _frame("unavailable", {"status": "unavailable"})
            return  # no cached payload or recover-and-replay on an invalid scope
        if loop.time() >= deadline:
            break  # a slow poll cannot extend the lifetime or emit after expiry
        current = json.dumps(
            {key: value for key, value in payload.items() if key != "observed_at"}, sort_keys=True
        )
        if current != fingerprint:
            fingerprint, sequence = current, sequence + 1
            yield _frame("snapshot", payload, sequence)
        now = loop.time()
        if now >= next_heartbeat:
            next_heartbeat = now + heartbeat
            yield ": keep-alive\n\n"
        await asyncio.sleep(max(0, min(poll, deadline - now, next_heartbeat - now)))
    yield _frame("close", {"reason": "reconnect"})


async def guarded_events(digest: str, read: Callable[[], dict], **options) -> AsyncIterator[str]:
    try:
        async for chunk in events(read, **options):
            yield chunk
    finally:
        capacity.leave(digest)
