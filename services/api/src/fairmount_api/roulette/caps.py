"""Stake validation and cap arithmetic (pure functions, no I/O)."""

from __future__ import annotations

from collections.abc import Iterable

from fairmount_api.core.errors import InvalidStake

ALLOWED_CHIPS = (5, 10, 50, 100, 500)
MIN_STAKE = 5
STAKE_UNIT = 5
PER_NUMBER_CAP = 2000  # straight-up + split exposure per underlying number
PER_SELECTION_CAP = 2000  # per exact outside / multi-number selection


def validate_stake(amount: object) -> int:
    """Return ``amount`` if it is a valid stake, otherwise raise :class:`InvalidStake`."""
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise InvalidStake()
    if amount < MIN_STAKE or amount % STAKE_UNIT != 0:
        raise InvalidStake()
    return amount


def accepted_amount(requested: int, remaining_capacities: Iterable[int]) -> int:
    """Largest valid amount within every remaining cap, rounded down to a multiple of 5.

    Returns 0 when nothing of at least the minimum stake can be accepted.
    """
    limit = min([requested, *remaining_capacities])
    limit = max(limit, 0)
    accepted = limit - (limit % STAKE_UNIT)
    return accepted if accepted >= MIN_STAKE else 0
