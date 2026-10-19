"""Pure POOL-01 funded-reserve admission arithmetic; never chooses an outcome.

Inputs MUST come from server-validated, locked accepted-bet/candidate projections,
not a client. This helper does not move points, accept a bet or prove concurrency
safety. The future DB service must atomically check and persist its inputs.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

EUROPEAN_OUTCOMES = 37


def _points(value: int, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        raise ValueError("Invalid nonnegative integer point amount")
    return value


@dataclass(frozen=True)
class RoundExposure:
    """Unsettled round totals including the proposed candidate, if any."""

    payout_by_number: tuple[int, ...]
    full_void_refund: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.payout_by_number, tuple)
            or len(self.payout_by_number) != EUROPEAN_OUTCOMES
        ):
            raise ValueError("Expected exactly 37 European outcome payouts")
        for payout in self.payout_by_number:
            _points(payout)
        _points(self.full_void_refund)

    @property
    def obligation(self) -> int:
        """Cover the larger of a number's total return and full-round void refunds."""
        return max(self.full_void_refund, max(self.payout_by_number))


def required_reserve(unsettled: Mapping[uuid.UUID, RoundExposure]) -> int:
    """Distinct unresolved rounds can settle/void independently; sum their maxima."""
    if not isinstance(unsettled, Mapping):
        raise ValueError("Expected a mapping of unsettled rounds")
    total = 0
    for round_id, exposure in unsettled.items():
        if not isinstance(round_id, uuid.UUID) or not isinstance(exposure, RoundExposure):
            raise ValueError("Invalid unsettled round exposure")
        total += exposure.obligation
    return total


def reserve_can_accept(
    current_balance: int,
    candidate_accepted_stake: int,
    resulting_unsettled: Mapping[uuid.UUID, RoundExposure],
) -> bool:
    """Check funded liability *after* the stake's proposed reserve transfer.

    False means reject the candidate in full for reserve insufficiency; no
    reserve-limited partial acceptance. Full wallet affordability, per-bet caps,
    canonical legal positions and cutoff are distinct prerequisites.
    """
    balance = _points(current_balance)
    stake = _points(candidate_accepted_stake, positive=True)
    obligation = required_reserve(resulting_unsettled)
    if (
        not resulting_unsettled
        or sum(exposure.full_void_refund for exposure in resulting_unsettled.values()) < stake
    ):
        raise ValueError("Candidate stake is absent from resulting refund exposure")
    return balance + stake >= obligation
