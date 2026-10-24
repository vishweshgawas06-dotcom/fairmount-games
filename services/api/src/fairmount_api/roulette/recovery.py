"""Private D-06a due-round transitions; no autonomous process is deployed.

The caller commits EACH returned step before calling again. In particular,
closing a round never settles it in the same transaction: close locks the round
only; settlement takes reserve -> round -> wallets. This prevents a lock-order
inversion against bet admission. A late result is independently selected and
persisted once, never replaced by a timeout void.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection, and_, func, or_, select

from fairmount_api.db.models import RouletteRound
from fairmount_api.roulette.round_clock import close_round, open_round
from fairmount_api.roulette.settlement import settle_round


@dataclass(frozen=True)
class DueRoundStep:
    round_id: uuid.UUID
    action: str  # RESULT_READY or SETTLED; not a payout route response
    winning_number: int


def advance_one_due_round(
    connection: Connection, *, _test_rng: Callable[[], int] | None = None
) -> DueRoundStep | None:
    """Process one overdue round using the DB clock, without auto-voiding.

    Selection is intentionally unlocked; each underlying transition acquires
    its own canonical row locks, rechecks state/time and is safe to retry after
    another worker commits. An OPEN result is persisted and returned; caller
    must COMMIT before a subsequent invocation attempts settlement.
    """
    now = connection.scalar(select(func.clock_timestamp()))
    row = connection.execute(
        select(RouletteRound.id, RouletteRound.state)
        .where(
            or_(
                and_(RouletteRound.state == "OPEN", RouletteRound.closes_at <= now),
                and_(RouletteRound.state == "CLOSED", RouletteRound.reveal_at <= now),
            )
        )
        .order_by(RouletteRound.closes_at, RouletteRound.id)
        .limit(1)
    ).one_or_none()
    if row is None:
        return None
    if row.state == "OPEN":
        winning = close_round(connection, row.id, _test_rng=_test_rng)
        return DueRoundStep(row.id, "RESULT_READY", winning)
    accounting = settle_round(connection, row.id)
    winning = connection.scalar(
        select(RouletteRound.winning_number).where(RouletteRound.id == row.id)
    )
    if accounting.state != "SETTLED" or winning is None:
        raise RuntimeError("Unsettled result must never be replaced with a void")
    return DueRoundStep(row.id, "SETTLED", winning)


def open_next_due_round(connection: Connection) -> uuid.UUID | None:
    """Open at most one fresh round after the previous scheduled reveal.

    No catch-up backfill on outage: a late worker resumes the prior result first,
    then starts a fresh 60-second round from *now*. A transaction advisory lock
    serializes two pollers without changing the reserve->round money lock order.
    The unique OPEN index is an additional database backstop.
    """
    connection.scalar(select(func.pg_advisory_xact_lock(725041, 1)))
    if connection.scalar(select(RouletteRound.id).where(RouletteRound.state == "OPEN")):
        return None
    last_reveal = connection.scalar(select(func.max(RouletteRound.reveal_at)))
    now = connection.scalar(select(func.clock_timestamp()))
    if last_reveal is not None and now < last_reveal:
        return None
    return open_round(connection)
