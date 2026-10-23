"""Internal PostgreSQL round clock and single independent result persistence.

No public route, worker/failover, recovery or settlement is wired yet. Run inside
one caller-owned transaction; never expose the test-only RNG override to clients.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import Connection, func, insert, select, update

from fairmount_api.db.models import RouletteRound


class RoundUnavailable(ValueError):
    """The round does not exist or cannot make this transition."""


def secure_random_pocket() -> int:
    """Uniform European pocket with no bet, wallet, reserve or identity inputs."""
    return secrets.randbelow(37)


def open_round(connection: Connection) -> uuid.UUID:
    """Open one global 60s round using the database clock, not client time."""
    now = connection.scalar(select(func.clock_timestamp()))
    return connection.execute(
        insert(RouletteRound.__table__)
        .values(
            state="OPEN",
            opens_at=now,
            closes_at=now + timedelta(seconds=50),
            reveal_at=now + timedelta(seconds=60),
        )
        .returning(RouletteRound.id)
    ).scalar_one()


def close_round(
    connection: Connection,
    round_id: uuid.UUID,
    *,
    _test_rng: Callable[[], int] | None = None,
) -> int:
    """At/after second 50, persist exactly one independent server result.

    Takes the round row lock and checks clock_timestamp() *after* it. Concurrent
    closes replay the stored outcome without rerolling. The private RNG hook is
    for deterministic tests only; never pass it from a request or worker config.
    """
    if not isinstance(round_id, uuid.UUID):
        raise RoundUnavailable("Round unavailable")
    row = connection.execute(
        select(RouletteRound.state, RouletteRound.closes_at, RouletteRound.winning_number)
        .where(RouletteRound.id == round_id)
        .with_for_update()
    ).one_or_none()
    if row is None or row.state == "VOID_REFUNDED":
        raise RoundUnavailable("Round unavailable")
    if row.state in ("CLOSED", "SETTLED"):
        if row.winning_number is None:
            raise RoundUnavailable("Round unavailable")
        return row.winning_number
    if row.state != "OPEN":
        raise RoundUnavailable("Round unavailable")
    now = connection.scalar(select(func.clock_timestamp()))
    if now < row.closes_at:
        raise RoundUnavailable("Round unavailable")
    winning = (_test_rng or secure_random_pocket)()
    if type(winning) is not int or not 0 <= winning <= 36:
        raise RuntimeError("Random source returned an invalid European pocket")
    connection.execute(
        update(RouletteRound.__table__)
        .where(RouletteRound.id == round_id)
        .values(state="CLOSED", winning_number=winning, result_set_at=now)
    )
    return winning
