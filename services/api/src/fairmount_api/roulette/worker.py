"""Opt-in, stateless D-06a poller; no web route or deployment is enabled.

Every database transition commits in its own transaction. Multiple supervised
processes can retry the same round through DB row/advisory locks; there is no
in-memory leader, no timeout void and no speculative client result. The operator
must configure a migrated PostgreSQL database, alerting and process supervision.
"""

from __future__ import annotations

import logging
import os
import signal
import uuid
from dataclasses import dataclass
from threading import Event
from urllib.parse import urlsplit

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from fairmount_api.roulette.recovery import (
    DueRoundStep,
    advance_one_due_round,
    open_next_due_round,
)
from fairmount_api.roulette.round_clock import RoundUnavailable
from fairmount_api.roulette.settlement import SettlementUnavailable

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class OpenedRound:
    id: uuid.UUID  # DB-generated, never client-supplied.


def run_once(engine: Engine) -> DueRoundStep | OpenedRound | None:
    """Commit ONE due transition, or open ONE newly due round, then return.

    This function deliberately does not settle a result it just persisted in
    the same transaction; admission locks reserve -> round and would otherwise
    deadlock with close's round lock. A subsequent call will settle it.
    """
    with engine.begin() as connection:
        step = advance_one_due_round(connection)
    if step is not None:
        return step
    with engine.begin() as connection:
        opened = open_next_due_round(connection)
    return OpenedRound(opened) if opened is not None else None


def poll(engine: Engine, stop: Event, *, interval: float = 1.0) -> None:
    """Retry transient failures without changing the result or terminal policy.

    An unresolved financial failure repeatedly alerts with bounded exponential
    backoff and *does not* open a new round until the due transition succeeds.
    The supervisor owns restarts and monitoring; this is not an SLO guarantee.
    """
    if not 0.1 <= interval <= 30:
        raise ValueError("Poll interval must be between 0.1 and 30 seconds")
    delay = interval
    while not stop.is_set():
        try:
            step = run_once(engine)
        except (SQLAlchemyError, SettlementUnavailable, RoundUnavailable) as exc:
            # Unexpected programming errors reach the supervisor, rather than
            # being hidden by an endless retry loop. Do not print SQL params.
            _LOG.error(
                "Roulette worker step failed (%s); keeping obligations open", type(exc).__name__
            )
            stop.wait(delay)
            delay = min(delay * 2, 30)
            continue
        delay = interval
        if step is not None:
            # Do not log the winning number ahead of the public reveal boundary.
            _LOG.info("Round transition committed: %s", type(step).__name__)
        else:
            stop.wait(interval)


def main() -> None:
    """Explicitly launched process, not an API startup hook or auto-enabled job."""
    raw_url = os.environ.get("FAIRMOUNT_WORKER_DATABASE_URL")
    if not raw_url or urlsplit(raw_url).scheme != "postgresql+psycopg":
        raise SystemExit("A PostgreSQL worker database URL must be set outside the repository")
    engine = create_engine(raw_url, pool_pre_ping=True)
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    logging.basicConfig(level=logging.INFO)
    try:
        with engine.connect() as connection:
            if connection.scalar(text("SELECT to_regclass('roulette_rounds')")) is None:
                raise SystemExit("Migrate the database before starting the round worker")
        poll(engine, stop)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
