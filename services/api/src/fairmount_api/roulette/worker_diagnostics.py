"""Read-only D-06a due-transition inventory for operators, never a scheduler.

An outstanding count is not a verdict on uptime or SLO compliance: the poller
has a normal scheduling delay and target thresholds remain unapproved. The
caller supplies a stable PostgreSQL snapshot and must not use these counts to
void a round, reroll a result or patch a wallet.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, case, func, select

from fairmount_api.db.models import RouletteRound


@dataclass(frozen=True)
class DueRoundInventory:
    observed_at: datetime
    due_open: int  # must persist one independent result, even if late
    due_closed: int  # must settle the already persisted result, even if late
    oldest_due_at: datetime | None
    latest_round_id: uuid.UUID | None
    latest_state: str | None
    latest_scheduled_reveal_at: datetime | None


def inspect_due_rounds(connection: Connection) -> DueRoundInventory:
    """Observe outstanding OPEN/CLOSED transitions using the database clock.

    Only public round-state fields are read, not private bets/balances, the RNG
    or the payout ledger. Neither state transition nor account mutation occurs.
    The caller should use REPEATABLE READ for a consistent read-only report.
    """
    now = connection.scalar(select(func.clock_timestamp()))
    due_open = (RouletteRound.state == "OPEN") & (RouletteRound.closes_at <= now)
    due_closed = (RouletteRound.state == "CLOSED") & (RouletteRound.reveal_at <= now)
    open_at = case((due_open, RouletteRound.closes_at))
    closed_at = case((due_closed, RouletteRound.reveal_at))
    totals = connection.execute(
        select(
            func.count().filter(due_open),
            func.count().filter(due_closed),
            func.min(func.least(open_at, closed_at)),
        )
    ).one()
    latest = connection.execute(
        select(RouletteRound.id, RouletteRound.state, RouletteRound.reveal_at)
        .order_by(RouletteRound.opens_at.desc(), RouletteRound.id.desc())
        .limit(1)
    ).one_or_none()
    return DueRoundInventory(
        observed_at=now,
        due_open=totals[0],
        due_closed=totals[1],
        oldest_due_at=totals[2],
        latest_round_id=latest.id if latest is not None else None,
        latest_state=latest.state if latest is not None else None,
        latest_scheduled_reveal_at=latest.reveal_at if latest is not None else None,
    )
