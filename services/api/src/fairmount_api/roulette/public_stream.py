"""Public, reveal-only server-sent event stream for the current round.

This is a *public* feed: it carries exactly the fields of the read-only snapshot
endpoint and nothing else. It never selects a bet, wallet, identity or the RNG
source, and it never reveals a persisted result before `reveal_at` — the
projection in `public_snapshot` owns that rule and this module only encodes it.

There is no replay contract and no game clock: a client may reconnect at any
time and receives the current public state again (`id` restarts per stream). The
stream self-closes after `MAX_SECONDS` so a client must re-establish it, which
keeps proxies and idle connections bounded. A database failure mid-stream ends
the stream with a generic `unavailable` event instead of inventing state.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import AsyncIterator, Callable

from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from fairmount_api.readiness import _configured_engine, schema_ready
from fairmount_api.roulette.public_payload import encode_snapshot
from fairmount_api.roulette.public_snapshot import read_public_round_snapshot

POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 15.0
RETRY_MILLISECONDS = 3000
MAX_SECONDS = 300.0
MAX_STREAMS = 64

_STREAM_HEADERS = {
    "Cache-Control": "no-store",
    "X-Accel-Buffering": "no",  # do not let a proxy buffer an event stream
    "Content-Type": "text/event-stream; charset=utf-8",
    "Connection": "keep-alive",
}


class StreamCapacityExceeded(RuntimeError):
    """Too many concurrent public streams; the caller answers 503 generically."""


class _Capacity:
    """Process-local cap: a stream holds one coroutine and one short DB poll."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.active = 0

    def enter(self) -> None:
        if self.active >= self.limit:
            raise StreamCapacityExceeded("Stream capacity exhausted")
        self.active += 1

    def leave(self) -> None:
        self.active = max(0, self.active - 1)


capacity = _Capacity(MAX_STREAMS)


def _snapshot_payload() -> tuple[str, str] | None:
    """Return (fingerprint, JSON data) or None when the public read is unavailable."""
    engine = _configured_engine()
    if engine is None:
        return None
    try:
        with engine.connect() as connection:
            if not schema_ready(connection):
                return None
            snapshot = read_public_round_snapshot(connection)
    except SQLAlchemyError:
        return None
    payload = encode_snapshot(snapshot)
    # Fingerprint only public fields; observed_at always changes and must not
    # cause a redundant event on every poll.
    fingerprint = json.dumps(
        {
            "round": payload["round"],
            "recent": payload["recent"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return fingerprint, json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _frame(*, event: str, data: str, identifier: int | None = None) -> str:
    lines = []
    if identifier is not None:
        lines.append(f"id: {identifier}")
    lines.append(f"event: {event}")
    lines.append(f"data: {data}")
    return "\n".join(lines) + "\n\n"


async def event_stream(
    *,
    poll_seconds: float | None = None,
    heartbeat_seconds: float | None = None,
    max_seconds: float | None = None,
    read: Callable[[], tuple[str, str] | None] | None = None,
) -> AsyncIterator[str]:
    """Yield reveal-safe `snapshot` events, skipping unchanged polls.

    Only a changed public payload produces an event; unchanged polls cost one
    database read and no client bytes until a heartbeat is due. `max_seconds`
    bounds the connection lifetime, and `read` is injectable purely for tests.
    """
    # Resolve at call time: a module-level rebinding (configuration or a test)
    # must be honoured, and an injected reader must actually be used.
    poll_seconds = POLL_SECONDS if poll_seconds is None else poll_seconds
    heartbeat_seconds = HEARTBEAT_SECONDS if heartbeat_seconds is None else heartbeat_seconds
    max_seconds = MAX_SECONDS if max_seconds is None else max_seconds
    read = _snapshot_payload if read is None else read
    for name, value in (
        ("poll_seconds", poll_seconds),
        ("heartbeat_seconds", heartbeat_seconds),
        ("max_seconds", max_seconds),
    ):
        if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
            raise ValueError(f"{name} must be a positive number")
    if poll_seconds > max_seconds or heartbeat_seconds > max_seconds:
        raise ValueError("poll and heartbeat intervals must fit inside max_seconds")

    counter = itertools.count(1)
    yield f"retry: {RETRY_MILLISECONDS}\n\n"
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max_seconds
    next_heartbeat = loop.time() + heartbeat_seconds
    last_fingerprint: str | None = None
    unavailable_sent = False
    while True:
        result = await run_in_threadpool(read)
        now = loop.time()
        if result is None:
            if not unavailable_sent:
                unavailable_sent = True
                yield _frame(event="unavailable", data='{"status":"unavailable"}')
            # Keep the stream open briefly: the database may recover on the
            # next poll, and reconnecting immediately would flood the API.
        else:
            fingerprint, data = result
            unavailable_sent = False
            if fingerprint != last_fingerprint:
                last_fingerprint = fingerprint
                yield _frame(event="snapshot", data=data, identifier=next(counter))
        if now >= deadline:
            yield _frame(event="close", data='{"reason":"reconnect"}')
            return
        if now >= next_heartbeat:
            next_heartbeat = now + heartbeat_seconds
            yield ": keep-alive\n\n"
        remaining = min(deadline - now, poll_seconds)
        await asyncio.sleep(max(0.0, min(remaining, next_heartbeat - now)))


def stream_headers() -> dict[str, str]:
    """Headers for an accepted event-stream response."""
    return dict(_STREAM_HEADERS)


async def guarded_stream(**options) -> AsyncIterator[str]:
    """Run `event_stream` while holding exactly one capacity slot.

    The slot is released in `finally`, which Starlette/uvicorn run on normal
    completion, error and client disconnect, so a dropped client cannot leak a
    slot. `capacity.enter()` is the caller's job so an over-capacity request can
    still answer 503 before any response body starts.
    """
    try:
        async for chunk in event_stream(**options):
            yield chunk
    finally:
        capacity.leave()
