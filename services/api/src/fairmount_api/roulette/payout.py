"""Total-payout convention approved 2026-10-14.

``total payout = winning stake x multiplier``. The multiplier already includes the returned
stake, so a 10-coin straight-up win credits 350 in total. The stake is debited when the bet is
accepted; on a win only the total payout is credited, and the stake is never added again.
"""

from __future__ import annotations

from fairmount_api.roulette.catalogue import BetType, Selection

MULTIPLIERS: dict[BetType, int] = {
    BetType.STRAIGHT: 35,
    BetType.SPLIT: 17,
    BetType.STREET: 11,
    BetType.CORNER: 8,
    BetType.SIX_LINE: 5,
    BetType.FIRST_FOUR: 8,
    BetType.DOZEN: 2,
    BetType.COLUMN: 2,
    BetType.RED: 1,
    BetType.BLACK: 1,
    BetType.ODD: 1,
    BetType.EVEN: 1,
    BetType.LOW: 1,
    BetType.HIGH: 1,
}


def total_payout(stake: int, selection: Selection, winning_number: int) -> int:
    """Total points credited for one bet (0 when it loses)."""
    if type(winning_number) is not int or not 0 <= winning_number <= 36:
        raise ValueError("winning_number must be an integer between 0 and 36")
    if type(stake) is not int or stake <= 0:
        raise ValueError("stake must be a positive integer")
    if winning_number not in selection.numbers:
        return 0
    return stake * MULTIPLIERS[selection.bet_type]
