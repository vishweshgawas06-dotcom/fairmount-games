"""Private read-only public-safe round projection; no HTTP/event contract yet.

The result exists internally at cutoff but must never appear in this projection
before reveal. Never select bets, balances, player identities or the RNG source.
D-08 still governs public event versioning, replay and delivery.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, func, select

from fairmount_api.db.models import RouletteRound


@dataclass(frozen=True)
class RevealedRound:
    round_id: uuid.UUID
    state: str
    winning_number: int | None  # None for an exceptional result-less void only


@dataclass(frozen=True)
class RoundSnapshot:
    observed_at: datetime  # authoritative database clock
    round_id: uuid.UUID | None
    phase: str  # IDLE, BETTING, SPINNING, RESULT_DELAYED, RESULT, VOID
    closes_at: datetime | None
    reveal_at: datetime | None
    winning_number: int | None  # never returned before reveal
    recent: tuple[RevealedRound, ...]


def read_public_round_snapshot(connection: Connection) -> RoundSnapshot:
    """Project at most 20 due-to-reveal results without selecting any private bet.

    An OPEN round past reveal is RESULT_DELAYED, never fabricated as a loss or
    void. CLOSED with persisted result is shown only at/after reveal even if
    settlement is delayed; settlement itself is handled by a separate worker.
    A client may display/animate this result but cannot choose it.
    """
    now = connection.scalar(select(func.clock_timestamp()))
    latest = connection.execute(
        select(
            RouletteRound.id,
            RouletteRound.state,
            RouletteRound.closes_at,
            RouletteRound.reveal_at,
            RouletteRound.winning_number,
        )
        .order_by(RouletteRound.opens_at.desc(), RouletteRound.id.desc())
        .limit(1)
    ).one_or_none()
    rows = connection.execute(
        select(RouletteRound.id, RouletteRound.state, RouletteRound.winning_number)
        .where(
            RouletteRound.reveal_at <= now,
            RouletteRound.state.in_(("CLOSED", "SETTLED", "VOID_REFUNDED")),
        )
        .order_by(RouletteRound.reveal_at.desc(), RouletteRound.id.desc())
        .limit(20)
    ).all()
    recent = tuple(RevealedRound(id_, state, number) for id_, state, number in rows)
    if latest is None:
        return RoundSnapshot(now, None, "IDLE", None, None, None, recent)
    if latest.state == "VOID_REFUNDED":
        phase = "VOID"
    elif now < latest.closes_at and latest.state == "OPEN":
        phase = "BETTING"
    elif now < latest.reveal_at:
        phase = "SPINNING"
    elif latest.state == "OPEN":
        phase = "RESULT_DELAYED"
    else:
        phase = "RESULT"
    number = latest.winning_number if phase == "RESULT" else None
    return RoundSnapshot(now, latest.id, phase, latest.closes_at, latest.reveal_at, number, recent)
